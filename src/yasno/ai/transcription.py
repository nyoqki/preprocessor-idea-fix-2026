from collections.abc import Awaitable, Callable
from typing import Any

from pydantic import BaseModel, Field, field_validator

from yasno.ai import prompts
from yasno.ai.parsing import JsonParseError, parse_model
from yasno.ai.types import ProviderError, TranscribedLine, Transcription


def _clamp(value: Any) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return 0.5
    return min(max(number, 0.0), 1.0)


class RawLine(BaseModel):
    latex: str = ""
    text: str = ""
    confidence: float = 1.0
    illegible: bool = False
    is_math: bool = True

    @field_validator("confidence", mode="before")
    @classmethod
    def _confidence(cls, value: Any) -> float:
        return _clamp(value)

    @field_validator("latex", "text", mode="before")
    @classmethod
    def _string(cls, value: Any) -> str:
        return "" if value is None else str(value)


class RawTranscription(BaseModel):
    task: str | None = None
    subject_hint: str | None = None
    is_math: bool = True
    illegible: bool = False
    lines: list[RawLine] = Field(default_factory=list)

    @field_validator("task", "subject_hint", mode="before")
    @classmethod
    def _optional(cls, value: Any) -> str | None:
        if value is None:
            return None
        text = str(value).strip()
        return None if not text or text.lower() == "null" else text


def to_transcription(raw: RawTranscription) -> Transcription:
    lines: list[TranscribedLine] = []
    for line in raw.lines:
        latex = line.latex.strip().strip("$").strip()
        text = line.text.strip()
        if not latex and not text:
            continue
        lines.append(
            TranscribedLine(
                index=len(lines) + 1,
                latex=latex,
                text=text,
                confidence=line.confidence,
                illegible=line.illegible or "\\square" in latex,
                is_math=line.is_math and bool(latex),
            )
        )
    math_lines = [line for line in lines if line.is_math]
    illegible = raw.illegible or (
        bool(math_lines) and sum(line.illegible for line in math_lines) * 2 > len(math_lines)
    )
    return Transcription(
        task=raw.task,
        lines=lines,
        is_math=raw.is_math and (bool(math_lines) or raw.task is not None),
        illegible=illegible,
        subject_hint=raw.subject_hint,
    )


def transcription_from_text(text: str) -> Transcription:
    return to_transcription(parse_model(RawTranscription, text))


async def transcription_with_repair(
    provider: str,
    raw: str,
    repair: Callable[[str], Awaitable[str]],
) -> Transcription:
    try:
        return transcription_from_text(raw)
    except JsonParseError as exc:
        instruction = prompts.REPAIR_JSON.format(error=exc)
    fixed = await repair(instruction)
    try:
        return transcription_from_text(fixed)
    except JsonParseError as exc:
        raise ProviderError(provider, f"malformed transcription: {exc}") from exc
