import json
from pathlib import Path

import pytest

from yasno.ai.eval import ProviderScore, load_samples, render, run, score_provider
from yasno.ai.fakes import DEFAULT_TRANSCRIPTION, FakeVision
from yasno.ai.types import ProviderError, TranscribedLine, Transcription
from yasno.config import Settings


def make_dataset(tmp_path: Path) -> None:
    (tmp_path / "a.jpg").write_bytes(b"\xff\xd8a")
    (tmp_path / "a.json").write_text(
        json.dumps({"lines": [{"latex": line.latex} for line in DEFAULT_TRANSCRIPTION.lines]})
    )
    (tmp_path / "b.png").write_bytes(b"\x89PNGb")
    (tmp_path / "b.json").write_text(json.dumps(["2x+3=7", "2x=4", "x=2"]))
    (tmp_path / "c.png").write_bytes(b"no reference")


def test_loads_only_images_with_references(tmp_path: Path) -> None:
    make_dataset(tmp_path)
    samples = load_samples(tmp_path)
    assert [s.image.name for s in samples] == ["a.jpg", "b.png"]
    assert samples[1].mime_type == "image/png"
    assert samples[1].expected == ["2x+3=7", "2x=4", "x=2"]


async def test_scores_line_accuracy_and_illegible_rate(tmp_path: Path) -> None:
    make_dataset(tmp_path)
    result = Transcription(
        lines=[
            TranscribedLine(index=1, latex="2x + 3 = 7"),
            TranscribedLine(index=2, latex="2x = 7 + 3"),
            TranscribedLine(index=3, latex="2x = \\square", illegible=True),
            TranscribedLine(index=4, latex="x = 5"),
        ]
    )
    score = await score_provider(FakeVision(result), load_samples(tmp_path))
    assert score.images == 2
    assert score.matched_lines == 3 + 1
    assert score.compared_lines == 4 + 4
    assert score.illegible_rate == pytest.approx(2 / 8)
    assert "fake:vision" in render([score])


async def test_counts_errors(tmp_path: Path) -> None:
    make_dataset(tmp_path)
    score = await score_provider(FakeVision(ProviderError("v", "down")), load_samples(tmp_path))
    assert score.errors == 2
    assert score.accuracy == 0.0


async def test_run_with_fake_settings(tmp_path: Path) -> None:
    make_dataset(tmp_path)
    scores = await run(tmp_path, Settings(_env_file=None, max_bot_token="t", ai_fake=True))
    assert isinstance(scores[0], ProviderScore)
    assert scores[0].images == 2
