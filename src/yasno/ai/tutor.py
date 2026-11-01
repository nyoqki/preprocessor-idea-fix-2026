import asyncio
import datetime as dt
import re
from collections.abc import Callable, Sequence
from datetime import date

import structlog
from pydantic import BaseModel, Field, field_validator

from yasno.ai import prompts
from yasno.ai.exams import (
    WEEKDAY_NAMES,
    detect_subject,
    exam_kind,
    looks_like_exam_announcement,
    resolve_exam_date,
)
from yasno.ai.latex import latex_to_plain
from yasno.ai.matching import attach_bboxes
from yasno.ai.parsing import JsonParseError, parse_model
from yasno.ai.registry import AiServices
from yasno.ai.resilience import AiUnavailableError
from yasno.ai.types import (
    ChatMessage,
    ChatModel,
    OcrEngine,
    OcrResult,
    ProviderError,
    Role,
    TranscribedLine,
    Transcription,
    VisionModel,
)
from yasno.math.display import humanize_math
from yasno.math.errors import ERROR_TITLES, ErrorType
from yasno.math.topics import TOPICS, TOPICS_BY_CODE

__all__ = [
    "ExamInfo",
    "Hint",
    "MaterialSummary",
    "TopicGuess",
    "Tutor",
    "looks_like_exam_announcement",
]

log = structlog.get_logger(__name__)

LeakCheck = Callable[[str], bool]

_ASSERTIVE = re.compile(r"неверн|неправильн|ты ошиб|у тебя ошиб|здесь ошибка|это ошибка", re.I)
_SHORT_FORBIDDEN = 2


class Hint(BaseModel):
    text: str
    question: str
    safe_fallback: bool = False

    @property
    def message(self) -> str:
        return f"{self.text}\n\n{self.question}".strip()

    def humanized(self) -> "Hint":
        return self.model_copy(
            update={"text": humanize_math(self.text), "question": humanize_math(self.question)}
        )


class TopicGuess(BaseModel):
    code: str | None = None
    confidence: float = Field(default=0.0, ge=0, le=1)


class ExamInfo(BaseModel):
    title: str
    subject: str | None = None
    date: dt.date | None = None
    topic_codes: list[str] = Field(default_factory=list)


class MaterialSummary(BaseModel):
    title: str
    topic_codes: list[str] = Field(default_factory=list)


class _HintReply(BaseModel):
    text: str
    question: str


class _TopicReply(BaseModel):
    code: str | None = None
    confidence: float = 0.5

    @field_validator("confidence", mode="before")
    @classmethod
    def _confidence(cls, value: object) -> float:
        try:
            number = float(str(value))
        except ValueError:
            return 0.5
        return min(max(number, 0.0), 1.0)


class _ExamReply(BaseModel):
    is_exam: bool = True
    subject: str | None = None
    title: str | None = None
    date: str | None = None
    topic_codes: list[str] = Field(default_factory=list)


class _SummaryReply(BaseModel):
    title: str
    topic_codes: list[str] = Field(default_factory=list)


def _topic_list() -> str:
    return "\n".join(f"- {topic.code}: {topic.title}" for topic in TOPICS)


def _known_topics(codes: Sequence[str]) -> list[str]:
    return list(dict.fromkeys(code for code in codes if code in TOPICS_BY_CODE))


def _render_lines(lines: Sequence[TranscribedLine]) -> str:
    rendered = []
    for line in lines:
        row = f"{line.index}. {line.latex}"
        if line.text:
            row += f" ({line.text})"
        if line.illegible:
            row += " [неразборчиво]"
        rendered.append(row)
    return "\n".join(rendered) or "—"


def _question(value: str) -> str:
    question = value.strip()
    if not question:
        return ""
    return question if question.endswith("?") else question.rstrip(".!") + "?"


def _contains(haystack: str, needle: str) -> bool:
    item = latex_to_plain(needle)
    if not item:
        return False
    if len(item) <= _SHORT_FORBIDDEN:
        return re.search(r"=" + re.escape(item) + r"(?![\d.])", haystack) is not None
    return item in haystack


class Tutor:
    def __init__(
        self,
        chat: ChatModel,
        vision: VisionModel | None = None,
        ocr: OcrEngine | None = None,
        *,
        max_material_chars: int = 6000,
        hint_regenerations: int = 2,
    ) -> None:
        self.chat = chat
        self.vision = vision
        self.ocr = ocr
        self._max_material_chars = max_material_chars
        self._hint_regenerations = hint_regenerations

    @classmethod
    def from_services(cls, services: AiServices) -> "Tutor":
        return cls(services.chat, services.vision, services.ocr)

    async def _ask_json[M: BaseModel](
        self,
        messages: list[ChatMessage],
        model: type[M],
        *,
        temperature: float = 0.2,
        max_tokens: int = 600,
    ) -> M:
        schema = model.model_json_schema()
        raw = await self.chat.complete(
            messages, json_schema=schema, temperature=temperature, max_tokens=max_tokens
        )
        try:
            return parse_model(model, raw)
        except JsonParseError as exc:
            log.warning("ai_json_repair", schema=model.__name__, error=str(exc))
            repair = [
                *messages,
                ChatMessage(role=Role.ASSISTANT, content=raw),
                ChatMessage(role=Role.USER, content=prompts.REPAIR_JSON.format(error=exc)),
            ]
        fixed = await self.chat.complete(
            repair, json_schema=schema, temperature=0.0, max_tokens=max_tokens
        )
        return parse_model(model, fixed)

    async def transcribe(self, image: bytes, mime_type: str) -> Transcription:
        if self.vision is None:
            raise AiUnavailableError("vision", [])
        ocr_task = asyncio.create_task(self.ocr.recognize(image, mime_type)) if self.ocr else None
        try:
            transcription = await self.vision.transcribe(image, mime_type)
        except BaseException:
            if ocr_task is not None:
                ocr_task.cancel()
            raise
        ocr = await self._ocr_result(ocr_task)
        if ocr is not None and transcription.lines:
            transcription.lines = attach_bboxes(transcription.lines, ocr)
        log.info(
            "ai_transcribed",
            lines=len(transcription.lines),
            illegible=transcription.illegible,
            is_math=transcription.is_math,
            with_bbox=sum(line.bbox is not None for line in transcription.lines),
            min_confidence=min((line.confidence for line in transcription.lines), default=None),
        )
        return transcription

    @staticmethod
    async def _ocr_result(task: "asyncio.Task[OcrResult] | None") -> OcrResult | None:
        if task is None:
            return None
        try:
            return await task
        except ProviderError as exc:
            log.warning("ai_ocr_skipped", error=str(exc))
            return None

    def _leaks(
        self,
        hint: Hint,
        forbidden: Sequence[str],
        leak_check: LeakCheck | None,
    ) -> bool:
        full = f"{hint.text}\n{hint.question}"
        if leak_check is not None and leak_check(full):
            return True
        normalized = latex_to_plain(full)
        return any(_contains(normalized, item) for item in forbidden)

    async def hint_for_error(
        self,
        task: str | None,
        lines: Sequence[TranscribedLine],
        first_error_step: int,
        error_type: ErrorType,
        expected_internal: str | None,
        grade: int,
        forbidden: Sequence[str] = (),
        leak_check: LeakCheck | None = None,
    ) -> Hint:
        line = next((item for item in lines if item.index == first_error_step), None)
        banned = [item for item in (*forbidden, expected_internal or "") if item.strip()]
        system = prompts.HINT_SYSTEM.format(persona=prompts.TUTOR_PERSONA.format(grade=grade))
        user = prompts.HINT_USER.format(
            task=task or "не указано",
            lines=_render_lines(lines),
            step=first_error_step,
            line=line.latex if line is not None else "—",
            error_title=ERROR_TITLES.get(error_type, ERROR_TITLES[ErrorType.OTHER]),
            expected=expected_internal or "нет",
        )
        for attempt in range(self._hint_regenerations + 1):
            content = system if attempt == 0 else f"{system}\n\n{prompts.HINT_STRICTER}"
            messages = [
                ChatMessage(role=Role.SYSTEM, content=content),
                ChatMessage(role=Role.USER, content=user),
            ]
            try:
                reply = await self._ask_json(messages, _HintReply, temperature=0.3 + 0.2 * attempt)
            except (ProviderError, JsonParseError) as exc:
                log.warning("ai_hint_failed", error=str(exc))
                break
            hint = Hint(text=reply.text.strip(), question=_question(reply.question))
            if not hint.text or not hint.question:
                continue
            if not self._leaks(hint, banned, leak_check):
                return hint.humanized()
            log.warning("ai_hint_leak", attempt=attempt + 1, error_type=error_type.value)
        return self.safe_hint(first_error_step, error_type)

    @staticmethod
    def safe_hint(step: int, error_type: ErrorType) -> Hint:
        title = ERROR_TITLES.get(error_type, ERROR_TITLES[ErrorType.OTHER])
        return Hint(
            text=prompts.SAFE_HINT_TEXT.format(step=step, title=title),
            question=prompts.SAFE_QUESTIONS.get(
                error_type, prompts.SAFE_QUESTIONS[ErrorType.OTHER]
            ),
            safe_fallback=True,
        )

    async def soft_review(
        self, task: str | None, lines: Sequence[TranscribedLine], grade: int
    ) -> Hint:
        system = prompts.SOFT_REVIEW_SYSTEM.format(
            persona=prompts.TUTOR_PERSONA.format(grade=grade)
        )
        messages = [
            ChatMessage(role=Role.SYSTEM, content=system),
            ChatMessage(
                role=Role.USER,
                content=prompts.SOFT_REVIEW_USER.format(
                    task=task or "не указано", lines=_render_lines(lines)
                ),
            ),
        ]
        for _ in range(2):
            try:
                reply = await self._ask_json(messages, _HintReply, temperature=0.4)
            except (ProviderError, JsonParseError) as exc:
                log.warning("ai_soft_review_failed", error=str(exc))
                break
            hint = Hint(text=reply.text.strip(), question=_question(reply.question))
            if hint.text and hint.question and not _ASSERTIVE.search(hint.message):
                return hint.humanized()
            log.warning("ai_soft_review_rejected")
        return Hint(
            text=prompts.SAFE_SOFT_TEXT, question=prompts.SAFE_SOFT_QUESTION, safe_fallback=True
        )

    async def classify_topic(
        self, task: str | None, lines: Sequence[TranscribedLine]
    ) -> TopicGuess:
        messages = [
            ChatMessage(
                role=Role.SYSTEM, content=prompts.CLASSIFY_SYSTEM.format(topics=_topic_list())
            ),
            ChatMessage(
                role=Role.USER,
                content=prompts.CLASSIFY_USER.format(
                    task=task or "не указано", lines=_render_lines(lines)
                ),
            ),
        ]
        try:
            reply = await self._ask_json(messages, _TopicReply, temperature=0.0, max_tokens=100)
        except (ProviderError, JsonParseError) as exc:
            log.warning("ai_topic_failed", error=str(exc))
            return TopicGuess()
        code = (reply.code or "").strip()
        if code not in TOPICS_BY_CODE:
            return TopicGuess()
        return TopicGuess(code=code, confidence=reply.confidence)

    async def extract_exam(self, text: str, today: date) -> ExamInfo | None:
        if not looks_like_exam_announcement(text):
            return None
        fallback = ExamInfo(
            title=exam_kind(text),
            subject=detect_subject(text),
            date=resolve_exam_date(text, today),
        )
        system = prompts.EXAM_SYSTEM.format(
            today=today.isoformat(), weekday=WEEKDAY_NAMES[today.weekday()], topics=_topic_list()
        )
        messages = [
            ChatMessage(role=Role.SYSTEM, content=system),
            ChatMessage(role=Role.USER, content=text),
        ]
        try:
            reply = await self._ask_json(messages, _ExamReply, temperature=0.0, max_tokens=300)
        except (ProviderError, JsonParseError) as exc:
            log.warning("ai_exam_failed", error=str(exc))
            return fallback
        if not reply.is_exam:
            return None
        return ExamInfo(
            title=(reply.title or "").strip() or fallback.title,
            subject=fallback.subject or (reply.subject or "").strip().lower() or None,
            date=fallback.date or _future_iso(reply.date, today),
            topic_codes=_known_topics(reply.topic_codes),
        )

    async def answer_question(
        self,
        question: str,
        materials: Sequence[str],
        grade: int,
        history: Sequence[ChatMessage] = (),
    ) -> str:
        system = prompts.ANSWER_SYSTEM.format(persona=prompts.TUTOR_PERSONA.format(grade=grade))
        messages = [ChatMessage(role=Role.SYSTEM, content=system)]
        context = self._materials(materials)
        if context:
            messages.append(
                ChatMessage(
                    role=Role.SYSTEM, content=prompts.ANSWER_MATERIALS.format(materials=context)
                )
            )
        messages.extend(history)
        messages.append(ChatMessage(role=Role.USER, content=question))
        try:
            answer = await self.chat.complete(messages, temperature=0.4, max_tokens=600)
        except ProviderError as exc:
            log.warning("ai_answer_failed", error=str(exc))
            return prompts.ANSWER_UNAVAILABLE
        return humanize_math(answer) or prompts.ANSWER_UNAVAILABLE

    def _materials(self, materials: Sequence[str]) -> str:
        budget = self._max_material_chars
        parts: list[str] = []
        for material in materials:
            chunk = material.strip()
            if not chunk or budget <= 0:
                continue
            chunk = chunk[:budget]
            budget -= len(chunk)
            parts.append(chunk)
        return "\n\n---\n\n".join(parts)

    async def summarize_material(self, ocr_text: str) -> MaterialSummary:
        text = ocr_text.strip()[: self._max_material_chars]
        first_line = next((row.strip() for row in text.splitlines() if row.strip()), "")
        fallback = MaterialSummary(title=first_line[:60] or "Конспект урока")
        if not text:
            return fallback
        messages = [
            ChatMessage(
                role=Role.SYSTEM, content=prompts.SUMMARY_SYSTEM.format(topics=_topic_list())
            ),
            ChatMessage(role=Role.USER, content=text),
        ]
        try:
            reply = await self._ask_json(messages, _SummaryReply, temperature=0.2, max_tokens=200)
        except (ProviderError, JsonParseError) as exc:
            log.warning("ai_summary_failed", error=str(exc))
            return fallback
        return MaterialSummary(
            title=reply.title.strip()[:80] or fallback.title,
            topic_codes=_known_topics(reply.topic_codes),
        )


def _future_iso(value: str | None, today: date) -> date | None:
    if not value:
        return None
    try:
        found = date.fromisoformat(value.strip())
    except ValueError:
        return None
    return found if found >= today else None
