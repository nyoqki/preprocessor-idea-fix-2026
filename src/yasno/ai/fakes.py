import hashlib
import math
from collections import deque
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field

from yasno.ai.types import (
    BoundingBox,
    ChatMessage,
    EmbeddingKind,
    JsonSchema,
    OcrLine,
    OcrResult,
    ProviderError,
    TranscribedLine,
    Transcription,
)

type ChatReply = str | ProviderError | Callable[[Sequence[ChatMessage]], str]

DEFAULT_TRANSCRIPTION = Transcription(
    task="Реши уравнение 2x + 3 = 7",
    lines=[
        TranscribedLine(index=1, latex="2x + 3 = 7", confidence=0.97),
        TranscribedLine(index=2, latex="2x = 7 + 3", confidence=0.95),
        TranscribedLine(index=3, latex="2x = 10", confidence=0.96),
        TranscribedLine(index=4, latex="x = 5", confidence=0.98),
    ],
    subject_hint="algebra",
)

DEFAULT_HINT = (
    '{"text": "Посмотри на вторую строку: когда слагаемое переходит в другую часть '
    'уравнения, с ним кое-что происходит.", '
    '"question": "Что меняется у числа, когда ты переносишь его через знак равенства?"}'
)

_DEV_REPLIES: tuple[tuple[str, str], ...] = (
    ("тему школьной задачи", '{"code": "alg.linear_eq", "confidence": 0.8}'),
    (
        "проверочной работе",
        '{"is_exam": true, "subject": "алгебра", "title": "Контрольная работа", '
        '"date": null, "topic_codes": []}',
    ),
    ("конспекта", '{"title": "Конспект урока", "topic_codes": ["alg.linear_eq"]}'),
    (
        "нельзя проверить",
        '{"text": "Давай пройдёмся по решению вместе.", '
        '"question": "Почему ты выбрал именно такой первый шаг?"}',
    ),
    ("проверка нашла", DEFAULT_HINT),
)


def dev_reply(messages: Sequence[ChatMessage]) -> str:
    system = " ".join(m.content for m in messages if m.role.value == "system")
    for marker, reply in _DEV_REPLIES:
        if marker in system:
            return reply
    return "Это тестовый ответ: подключи настоящего провайдера, чтобы получить объяснение."


@dataclass
class FakeChat:
    replies: Iterable[ChatReply] = ()
    default: ChatReply = dev_reply
    name: str = "fake:chat"
    calls: list[list[ChatMessage]] = field(default_factory=list)
    schemas: list[JsonSchema | None] = field(default_factory=list)

    def __post_init__(self) -> None:
        self._queue: deque[ChatReply] = deque(self.replies)

    def push(self, *replies: ChatReply) -> None:
        self._queue.extend(replies)

    async def complete(
        self,
        messages: Sequence[ChatMessage],
        *,
        json_schema: JsonSchema | None = None,
        temperature: float = 0.2,
        max_tokens: int = 800,
    ) -> str:
        self.calls.append(list(messages))
        self.schemas.append(json_schema)
        reply = self._queue.popleft() if self._queue else self.default
        if isinstance(reply, ProviderError):
            raise reply
        if callable(reply):
            return reply(messages)
        return reply


@dataclass
class FakeVision:
    result: Transcription | ProviderError = field(
        default_factory=lambda: DEFAULT_TRANSCRIPTION.model_copy(deep=True)
    )
    name: str = "fake:vision"
    calls: int = 0

    async def transcribe(self, image: bytes, mime_type: str) -> Transcription:
        self.calls += 1
        if isinstance(self.result, ProviderError):
            raise self.result
        return self.result.model_copy(deep=True)


@dataclass
class FakeOcr:
    result: OcrResult | ProviderError | None = None
    name: str = "fake:ocr"
    calls: int = 0

    async def recognize(self, image: bytes, mime_type: str) -> OcrResult:
        self.calls += 1
        if isinstance(self.result, ProviderError):
            raise self.result
        if self.result is not None:
            return self.result.model_copy(deep=True)
        lines = DEFAULT_TRANSCRIPTION.lines
        step = 1 / (len(lines) + 1)
        return OcrResult(
            lines=[
                OcrLine(
                    text=line.latex,
                    bbox=BoundingBox(x=0.1, y=step * i, width=0.6, height=step * 0.8),
                )
                for i, line in enumerate(lines, start=1)
            ]
        )


@dataclass
class FakeEmbedder:
    dimensions: int = 32
    name: str = "fake:embedder"

    def _vector(self, text: str, kind: EmbeddingKind) -> list[float]:
        values: list[float] = []
        counter = 0
        while len(values) < self.dimensions:
            digest = hashlib.sha256(f"{counter}:{text.lower().strip()}".encode()).digest()
            values.extend((byte - 127.5) / 127.5 for byte in digest)
            counter += 1
        vector = values[: self.dimensions]
        norm = math.sqrt(sum(value * value for value in vector)) or 1.0
        return [value / norm for value in vector]

    async def embed(self, texts: Sequence[str], *, kind: EmbeddingKind) -> list[list[float]]:
        return [self._vector(text, kind) for text in texts]
