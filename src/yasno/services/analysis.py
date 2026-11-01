import asyncio
import hashlib
import multiprocessing
from collections.abc import Sequence
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass, field
from datetime import timedelta
from enum import StrEnum
from typing import Any

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from yasno.ai.tutor import Hint, Tutor
from yasno.ai.types import ProviderError, TranscribedLine, Transcription
from yasno.clock import utcnow
from yasno.db.models import Submission, SubmissionKind, SubmissionStatus
from yasno.math.display import to_display
from yasno.math.errors import ErrorType
from yasno.math.leak import reveals_answer
from yasno.math.verification import ProblemKind, Status, Verification
from yasno.math.verify import verify_solution
from yasno.media import SUPPORTED_FOR_RECOGNITION, image_key, sniff_image_type
from yasno.services import progress
from yasno.storage import Storage

log = structlog.get_logger(__name__)

LOW_CONFIDENCE = 0.6
VERIFY_TIMEOUT_SECONDS = 15.0
DUPLICATE_WINDOW = timedelta(hours=12)

FALLBACK_TOPICS: dict[ProblemKind, str] = {
    ProblemKind.EQUATION: "alg.linear_eq",
    ProblemKind.INEQUALITY: "alg.linear_ineq",
    ProblemKind.SYSTEM: "alg.systems",
    ProblemKind.EXPRESSION: "alg.expressions",
    ProblemKind.DERIVATIVE: "calc.derivative",
}


class Verdict(StrEnum):
    CORRECT = "correct"
    ERROR = "error"
    INCOMPLETE = "incomplete"
    REVIEW = "review"
    CONFIRM = "confirm"
    UNREADABLE = "unreadable"
    NOT_MATH = "not_math"
    UNSUPPORTED_FORMAT = "unsupported_format"


@dataclass(slots=True)
class Analysis:
    verdict: Verdict
    submission_id: int | None = None
    task: str | None = None
    lines: list[TranscribedLine] = field(default_factory=list)
    error_line: TranscribedLine | None = None
    error_type: ErrorType | None = None
    topic_code: str | None = None
    hint: Hint | None = None
    doubtful: list[TranscribedLine] = field(default_factory=list)


class Verifier:
    def __init__(self, workers: int = 2) -> None:
        self._pool = ProcessPoolExecutor(
            max_workers=workers, mp_context=multiprocessing.get_context("forkserver")
        )

    async def verify(self, lines: Sequence[str], task: str | None) -> Verification:
        loop = asyncio.get_running_loop()
        future = loop.run_in_executor(self._pool, verify_solution, list(lines), task)
        try:
            return await asyncio.wait_for(future, VERIFY_TIMEOUT_SECONDS)
        except TimeoutError:
            log.warning("verification_timeout", lines=len(lines))
            return Verification(status=Status.UNSUPPORTED, problem_kind=ProblemKind.UNKNOWN)

    def close(self) -> None:
        self._pool.shutdown(wait=False, cancel_futures=True)


@dataclass(frozen=True, slots=True)
class AnalysisDeps:
    sessions: async_sessionmaker[AsyncSession]
    storage: Storage
    tutor: Tutor
    verifier: Verifier


def math_lines(transcription: Transcription) -> list[TranscribedLine]:
    return [line for line in transcription.lines if line.is_math and line.latex.strip()]


def doubtful_lines(lines: Sequence[TranscribedLine]) -> list[TranscribedLine]:
    return [line for line in lines if line.illegible or line.confidence < LOW_CONFIDENCE]


def display(line: TranscribedLine) -> str:
    return to_display(line.latex) if line.latex else line.text


async def _duplicate(session: AsyncSession, user_id: int, digest: str) -> Submission | None:
    result = await session.execute(
        select(Submission)
        .where(
            Submission.user_id == user_id,
            Submission.image_sha256 == digest,
            Submission.status == SubmissionStatus.DONE,
            Submission.created_at >= utcnow() - DUPLICATE_WINDOW,
        )
        .order_by(Submission.created_at.desc())
        .limit(1)
    )
    return result.scalar_one_or_none()


async def start_submission(
    deps: AnalysisDeps, *, user_id: int, image: bytes, source_mid: str | None
) -> tuple[Submission | None, str]:
    content_type = sniff_image_type(image)
    if content_type not in SUPPORTED_FOR_RECOGNITION:
        return None, content_type
    digest = hashlib.sha256(image).hexdigest()
    async with deps.sessions.begin() as session:
        duplicate = await _duplicate(session, user_id, digest)
        if duplicate is not None:
            return duplicate, content_type
        key = image_key("homework", user_id, content_type)
        await deps.storage.put(key, image, content_type)
        submission = Submission(
            user_id=user_id,
            kind=SubmissionKind.HOMEWORK,
            status=SubmissionStatus.PROCESSING,
            image_key=key,
            image_sha256=digest,
            source_mid=source_mid,
        )
        session.add(submission)
        await session.flush()
        return submission, content_type


async def _save(
    deps: AnalysisDeps,
    submission_id: int,
    status: SubmissionStatus,
    *,
    transcription: Transcription | None = None,
    analysis: dict[str, Any] | None = None,
    topic_code: str | None = None,
    error: str | None = None,
) -> None:
    async with deps.sessions.begin() as session:
        submission = await session.get(Submission, submission_id)
        if submission is None:
            return
        submission.status = status
        if transcription is not None:
            submission.transcription = transcription.model_dump(mode="json")
        if analysis is not None:
            submission.analysis = analysis
        if topic_code is not None:
            submission.topic_code = topic_code
        submission.error = error
        if status in (SubmissionStatus.DONE, SubmissionStatus.FAILED):
            submission.finished_at = utcnow()


async def transcribe(
    deps: AnalysisDeps, submission_id: int, image: bytes, content_type: str
) -> Analysis:
    try:
        transcription = await deps.tutor.transcribe(image, content_type)
    except ProviderError as exc:
        await _save(deps, submission_id, SubmissionStatus.FAILED, error=str(exc))
        raise
    lines = math_lines(transcription)
    if transcription.illegible or not transcription.is_math or not lines:
        verdict = (
            Verdict.NOT_MATH
            if not transcription.is_math and not transcription.illegible
            else Verdict.UNREADABLE
        )
        await _save(
            deps,
            submission_id,
            SubmissionStatus.FAILED,
            transcription=transcription,
            analysis={"status": verdict.value},
        )
        return Analysis(verdict, submission_id)
    doubtful = doubtful_lines(lines)
    status = SubmissionStatus.NEEDS_CONFIRMATION if doubtful else SubmissionStatus.PROCESSING
    await _save(deps, submission_id, status, transcription=transcription)
    verdict = Verdict.CONFIRM if doubtful else Verdict.REVIEW
    return Analysis(verdict, submission_id, task=transcription.task, lines=lines, doubtful=doubtful)


async def load_transcription(deps: AnalysisDeps, submission_id: int) -> Transcription | None:
    async with deps.sessions() as session:
        submission = await session.get(Submission, submission_id)
        if submission is None or not isinstance(submission.transcription, dict):
            return None
        return Transcription.model_validate(submission.transcription)


async def correct_line(
    deps: AnalysisDeps, submission_id: int, index: int, latex: str
) -> Transcription | None:
    transcription = await load_transcription(deps, submission_id)
    if transcription is None:
        return None
    for line in transcription.lines:
        if line.index == index:
            line.latex = latex
            line.text = latex
            line.confidence = 1.0
            line.illegible = False
    await _save(deps, submission_id, SubmissionStatus.PROCESSING, transcription=transcription)
    return transcription


async def evaluate(deps: AnalysisDeps, *, submission_id: int, user_id: int, grade: int) -> Analysis:
    transcription = await load_transcription(deps, submission_id)
    if transcription is None:
        return Analysis(Verdict.UNREADABLE, submission_id)
    lines = math_lines(transcription)
    latex = [line.latex for line in lines]
    verification = await deps.verifier.verify(latex, transcription.task)
    guess = await deps.tutor.classify_topic(transcription.task, lines)
    topic = guess.code or FALLBACK_TOPICS.get(verification.problem_kind)
    result = Analysis(
        Verdict.REVIEW,
        submission_id,
        task=transcription.task,
        lines=lines,
        topic_code=topic,
    )
    now = utcnow()

    if verification.status is Status.CORRECT:
        result.verdict = Verdict.CORRECT
        if topic is not None:
            async with deps.sessions.begin() as session:
                await progress.record_success(session, user_id=user_id, topic_code=topic, now=now)
    elif verification.status is Status.INCOMPLETE:
        result.verdict = Verdict.INCOMPLETE
    elif verification.status is Status.UNPARSEABLE and verification.unparseable_step is not None:
        position = verification.unparseable_step
        if 0 <= position < len(lines):
            result.verdict = Verdict.CONFIRM
            result.doubtful = [lines[position]]
            await _save(
                deps,
                submission_id,
                SubmissionStatus.NEEDS_CONFIRMATION,
                topic_code=topic,
            )
            return result
    elif verification.status is Status.ERROR and verification.first_error_step is not None:
        position = min(max(verification.first_error_step, 0), len(lines) - 1)
        error_line = lines[position]
        error_type = verification.error_type or ErrorType.OTHER
        result.verdict = Verdict.ERROR
        result.error_line = error_line
        result.error_type = error_type
        context = [line.latex for line in lines]
        result.hint = await deps.tutor.hint_for_error(
            transcription.task,
            lines,
            error_line.index,
            error_type,
            verification.expected,
            grade,
            forbidden=[v for v in (verification.final_answer, verification.solution) if v],
            leak_check=lambda text: reveals_answer(text, verification, context=context),
        )
        if topic is not None:
            async with deps.sessions.begin() as session:
                await progress.record_mistake(
                    session,
                    user_id=user_id,
                    topic_code=topic,
                    error_type=error_type,
                    now=now,
                    submission_id=submission_id,
                    step_index=error_line.index,
                    detail={"line": error_line.latex},
                )

    if result.verdict is Verdict.REVIEW:
        result.hint = await deps.tutor.soft_review(transcription.task, lines, grade)

    await _save(
        deps,
        submission_id,
        SubmissionStatus.DONE,
        topic_code=topic,
        analysis={
            "status": result.verdict.value,
            "verification": verification.status.value,
            "problem_kind": verification.problem_kind.value,
            "first_error_step": result.error_line.index if result.error_line else None,
            "error_type": result.error_type.value if result.error_type else None,
            "hint": result.hint.message if result.hint else None,
        },
    )
    log.info(
        "submission_evaluated",
        submission_id=submission_id,
        verdict=result.verdict.value,
        verification=verification.status.value,
        topic=topic,
        error_type=result.error_type.value if result.error_type else None,
    )
    return result
