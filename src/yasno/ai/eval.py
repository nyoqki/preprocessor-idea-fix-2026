import argparse
import asyncio
import json
import sys
import time
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from yasno.ai.fakes import FakeVision
from yasno.ai.latex import normalize_latex
from yasno.ai.registry import AiConfigurationError, build_provider_sets
from yasno.ai.resilience import ResilientVision, RetryPolicy
from yasno.ai.types import ProviderError, Transcription, VisionModel
from yasno.config import Settings

IMAGE_TYPES = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png"}


@dataclass(frozen=True, slots=True)
class Sample:
    image: Path
    mime_type: str
    expected: list[str]


@dataclass
class ProviderScore:
    name: str
    images: int = 0
    errors: int = 0
    matched_lines: int = 0
    compared_lines: int = 0
    predicted_lines: int = 0
    illegible_lines: int = 0
    latencies: list[float] = field(default_factory=list)

    @property
    def accuracy(self) -> float:
        return self.matched_lines / self.compared_lines if self.compared_lines else 0.0

    @property
    def illegible_rate(self) -> float:
        return self.illegible_lines / self.predicted_lines if self.predicted_lines else 0.0

    @property
    def mean_latency(self) -> float:
        return sum(self.latencies) / len(self.latencies) if self.latencies else 0.0

    @property
    def max_latency(self) -> float:
        return max(self.latencies, default=0.0)

    def add(self, expected: Sequence[str], result: Transcription, latency: float) -> None:
        self.images += 1
        self.latencies.append(latency)
        predicted = [line.latex for line in result.lines if line.is_math]
        self.matched_lines += sum(
            normalize_latex(a) == normalize_latex(b)
            for a, b in zip(expected, predicted, strict=False)
        )
        self.compared_lines += max(len(expected), len(predicted))
        self.predicted_lines += len(result.lines)
        self.illegible_lines += sum(line.illegible for line in result.lines)


def expected_lines(data: Any) -> list[str]:
    items = data.get("lines", []) if isinstance(data, dict) else data
    if not isinstance(items, list):
        raise ValueError("expected a list of lines")
    lines: list[str] = []
    for item in items:
        if isinstance(item, str):
            lines.append(item)
        elif isinstance(item, dict) and item.get("is_math", True):
            lines.append(str(item.get("latex", "")))
    return lines


def load_samples(directory: Path) -> list[Sample]:
    samples = []
    for image in sorted(directory.iterdir()):
        mime_type = IMAGE_TYPES.get(image.suffix.lower())
        reference = image.with_suffix(".json")
        if mime_type is None or not reference.exists():
            continue
        data = json.loads(reference.read_text(encoding="utf-8"))
        samples.append(Sample(image, mime_type, expected_lines(data)))
    return samples


async def score_provider(model: VisionModel, samples: Sequence[Sample]) -> ProviderScore:
    score = ProviderScore(model.name)
    for sample in samples:
        started = time.monotonic()
        try:
            result = await model.transcribe(sample.image.read_bytes(), sample.mime_type)
        except ProviderError as exc:
            score.errors += 1
            print(f"  {model.name}: {sample.image.name}: {exc}", file=sys.stderr)
            continue
        score.add(sample.expected, result, time.monotonic() - started)
    return score


def render(scores: Sequence[ProviderScore]) -> str:
    header = f"{'provider':<36} {'images':>6} {'errors':>6} {'line_acc':>8} {'illegible':>9} "
    header += f"{'avg_s':>7} {'max_s':>7}"
    rows = [header, "-" * len(header)]
    for s in scores:
        rows.append(
            f"{s.name:<36} {s.images:>6} {s.errors:>6} {s.accuracy:>8.1%} "
            f"{s.illegible_rate:>9.1%} {s.mean_latency:>7.2f} {s.max_latency:>7.2f}"
        )
    return "\n".join(rows)


def vision_models(settings: Settings) -> tuple[list[VisionModel], list[Any]]:
    if settings.ai_fake:
        return [FakeVision()], []
    sets = build_provider_sets(settings)
    policy = RetryPolicy(attempts=settings.ai_max_attempts, timeout=settings.ai_timeout_seconds)
    return [ResilientVision(item.vision, policy) for item in sets if item.vision], sets


async def run(directory: Path, settings: Settings) -> list[ProviderScore]:
    samples = load_samples(directory)
    if not samples:
        raise SystemExit(f"no images with sibling .json references in {directory}")
    models, sets = vision_models(settings)
    try:
        return [await score_provider(model, samples) for model in models]
    finally:
        for item in sets:
            if item.close is not None:
                await item.close()


def main(argv: Sequence[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        prog="python -m yasno.ai.eval",
        description="Сравнение vision-провайдеров на размеченных фото решений",
    )
    parser.add_argument("directory", type=Path)
    args = parser.parse_args(argv)
    try:
        scores = asyncio.run(run(args.directory, Settings()))
    except AiConfigurationError as exc:
        raise SystemExit(str(exc)) from exc
    print(render(scores))


if __name__ == "__main__":
    main()
