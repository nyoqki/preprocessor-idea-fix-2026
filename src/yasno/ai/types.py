from collections.abc import Sequence
from enum import StrEnum
from typing import Any, Literal, Protocol

from pydantic import BaseModel, Field


class BoundingBox(BaseModel):
    x: float = Field(ge=0, le=1)
    y: float = Field(ge=0, le=1)
    width: float = Field(ge=0, le=1)
    height: float = Field(ge=0, le=1)


class TranscribedLine(BaseModel):
    index: int
    latex: str
    text: str = ""
    confidence: float = Field(default=1.0, ge=0, le=1)
    bbox: BoundingBox | None = None


class Transcription(BaseModel):
    task: str | None = None
    lines: list[TranscribedLine] = Field(default_factory=list)
    is_math: bool = True
    illegible: bool = False
    subject_hint: str | None = None


class OcrLine(BaseModel):
    text: str
    bbox: BoundingBox | None = None


class OcrResult(BaseModel):
    lines: list[OcrLine] = Field(default_factory=list)

    @property
    def text(self) -> str:
        return "\n".join(line.text for line in self.lines)


class Role(StrEnum):
    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"


class ChatMessage(BaseModel):
    role: Role
    content: str


type EmbeddingKind = Literal["document", "query"]
type JsonSchema = dict[str, Any]


class ProviderError(Exception):
    def __init__(self, provider: str, message: str, *, retryable: bool = False) -> None:
        super().__init__(f"{provider}: {message}")
        self.provider = provider
        self.retryable = retryable


class VisionModel(Protocol):
    name: str

    async def transcribe(self, image: bytes, mime_type: str) -> Transcription: ...


class ChatModel(Protocol):
    name: str

    async def complete(
        self,
        messages: Sequence[ChatMessage],
        *,
        json_schema: JsonSchema | None = None,
        temperature: float = 0.2,
        max_tokens: int = 800,
    ) -> str: ...


class Embedder(Protocol):
    name: str
    dimensions: int

    async def embed(self, texts: Sequence[str], *, kind: EmbeddingKind) -> list[list[float]]: ...


class OcrEngine(Protocol):
    name: str

    async def recognize(self, image: bytes, mime_type: str) -> OcrResult: ...
