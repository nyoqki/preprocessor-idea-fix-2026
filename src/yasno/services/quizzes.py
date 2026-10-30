import random
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from yasno.db.models import Exam, Mistake, Quiz, QuizItem, QuizReason, QuizStatus, User
from yasno.math.display import to_display
from yasno.math.errors import ERROR_TITLES, ErrorType
from yasno.math.generators import generate, supported_topics
from yasno.services import exams, progress

EXAM_QUIZ_SIZE = 5
REVIEW_QUIZ_SIZE = 3
GRADE_DEFAULTS: dict[int, tuple[str, ...]] = {
    8: ("alg.quadratic_eq", "alg.roots", "alg.rational_expr"),
    9: ("alg.quadratic_ineq", "alg.systems", "alg.progressions"),
    10: ("alg.exponential", "alg.logarithms", "alg.irrational_eq"),
    11: ("calc.derivative", "alg.logarithms", "alg.exponential"),
}


class QuizError(Exception):
    pass


class QuizNotFoundError(QuizError):
    pass


class QuizClosedError(QuizError):
    pass


class InvalidChoiceError(QuizError):
    pass


@dataclass(frozen=True, slots=True)
class AnswerResult:
    item: QuizItem
    quiz: Quiz
    chosen_index: int
    already_answered: bool

    @property
    def is_correct(self) -> bool:
        return self.chosen_index == self.item.correct_index

    @property
    def explanation(self) -> str | None:
        choice = choice_at(self.item, self.chosen_index)
        value = choice.get("explanation")
        return value if isinstance(value, str) else None

    @property
    def answered(self) -> int:
        return sum(1 for item in self.quiz.items if item.answered_index is not None)

    @property
    def correct(self) -> int:
        return sum(1 for item in self.quiz.items if item.answered_index == item.correct_index)


def choice_at(item: QuizItem, index: int) -> dict[str, object]:
    if 0 <= index < len(item.choices) and isinstance(item.choices[index], dict):
        return item.choices[index]
    return {}


def _parse_error_type(value: object) -> ErrorType | None:
    try:
        return ErrorType(value) if isinstance(value, str) else None
    except ValueError:
        return None


async def _typical_error(session: AsyncSession, user_id: int, topic: str) -> ErrorType | None:
    rows = await session.execute(
        select(Mistake.error_type).where(Mistake.user_id == user_id, Mistake.topic_code == topic)
    )
    counts = Counter(rows.scalars())
    for value, _ in counts.most_common():
        parsed = _parse_error_type(value)
        if parsed is not None and parsed is not ErrorType.OTHER:
            return parsed
    return None


def plan_topics(
    exam_topics: Sequence[str], gap_topics: Sequence[str], grade: int | None, size: int
) -> list[str]:
    supported = supported_topics()
    exam = [t for t in dict.fromkeys(exam_topics) if t in supported]
    gaps = [t for t in dict.fromkeys(gap_topics) if t in supported]
    base = exam or [t for t in GRADE_DEFAULTS.get(grade or 9, ()) if t in supported]
    personal = [t for t in gaps if t in exam] or gaps
    plan: list[str] = []
    pools = [personal, base] if personal else [base]
    while len(plan) < size and any(pools):
        for pool in pools:
            if pool and len(plan) < size:
                plan.append(pool[len(plan) % len(pool)])
    return plan or sorted(supported)[:size]


async def _expire_active(session: AsyncSession, user_id: int) -> None:
    await session.execute(
        update(Quiz)
        .where(Quiz.user_id == user_id, Quiz.status == QuizStatus.ACTIVE)
        .values(status=QuizStatus.EXPIRED)
    )


async def build_quiz(
    session: AsyncSession,
    user: User,
    *,
    reason: QuizReason,
    topics: Sequence[str],
    exam: Exam | None = None,
    rng: random.Random | None = None,
) -> Quiz:
    rng = rng or random.Random()  # noqa: S311
    await _expire_active(session, user.id)
    quiz = Quiz(user_id=user.id, exam_id=exam.id if exam else None, reason=reason)
    focus_cache: dict[str, ErrorType | None] = {}
    for position, topic in enumerate(topics):
        if topic not in focus_cache:
            focus_cache[topic] = await _typical_error(session, user.id, topic)
        problem = generate(topic, rng, difficulty=1, focus=focus_cache[topic])
        choices = list(problem.choices)
        rng.shuffle(choices)
        quiz.items.append(
            QuizItem(
                position=position,
                topic_code=topic,
                prompt=f"{problem.instruction}: {to_display(problem.prompt_latex)}",
                choices=[
                    {
                        "latex": choice.latex,
                        "text": to_display(choice.latex),
                        "error_type": choice.error_type.value if choice.error_type else None,
                        "explanation": (
                            f"Похоже на ошибку: {ERROR_TITLES[choice.error_type].lower()}."
                            if choice.error_type
                            else None
                        ),
                    }
                    for choice in choices
                ],
                correct_index=next(i for i, c in enumerate(choices) if c.correct),
            )
        )
    session.add(quiz)
    await session.flush()
    return quiz


async def exam_quiz(session: AsyncSession, user: User, exam: Exam) -> Quiz:
    gaps = await progress.weakest_topics(session, user.id, limit=5)
    topics = plan_topics(exam.topic_codes, gaps, user.grade, EXAM_QUIZ_SIZE)
    return await build_quiz(session, user, reason=QuizReason.EXAM, topics=topics, exam=exam)


async def personal_quiz(session: AsyncSession, user: User, today: date) -> Quiz:
    upcoming = await exams.upcoming_for_user(session, user, today)
    exam = upcoming[0] if upcoming else None
    gaps = await progress.weakest_topics(session, user.id, limit=5)
    topics = plan_topics(exam.topic_codes if exam else [], gaps, user.grade, EXAM_QUIZ_SIZE)
    return await build_quiz(session, user, reason=QuizReason.MANUAL, topics=topics, exam=exam)


async def topic_quiz(session: AsyncSession, user: User, topic: str, reason: QuizReason) -> Quiz:
    if topic not in supported_topics():
        raise QuizNotFoundError(topic)
    return await build_quiz(session, user, reason=reason, topics=[topic] * REVIEW_QUIZ_SIZE)


async def load_quiz(session: AsyncSession, quiz_id: int, user_id: int) -> Quiz:
    result = await session.execute(
        select(Quiz)
        .where(Quiz.id == quiz_id, Quiz.user_id == user_id)
        .options(selectinload(Quiz.items))
        .execution_options(populate_existing=True)
    )
    quiz = result.scalar_one_or_none()
    if quiz is None:
        raise QuizNotFoundError(quiz_id)
    return quiz


def next_item(quiz: Quiz) -> QuizItem | None:
    return next((item for item in quiz.items if item.answered_index is None), None)


async def answer_item(
    session: AsyncSession,
    *,
    user_id: int,
    quiz_id: int,
    item_id: int,
    choice_index: int,
    now: datetime,
) -> AnswerResult:
    result = await session.execute(
        select(QuizItem)
        .join(Quiz, Quiz.id == QuizItem.quiz_id)
        .where(QuizItem.id == item_id, QuizItem.quiz_id == quiz_id, Quiz.user_id == user_id)
        .with_for_update(of=QuizItem)
        .execution_options(populate_existing=True)
    )
    item = result.scalar_one_or_none()
    if item is None:
        raise QuizNotFoundError(item_id)
    quiz = await load_quiz(session, quiz_id, user_id)
    if item.answered_index is not None:
        return AnswerResult(item, quiz, item.answered_index, already_answered=True)
    if quiz.status is not QuizStatus.ACTIVE:
        raise QuizClosedError(quiz_id)
    if not 0 <= choice_index < len(item.choices):
        raise InvalidChoiceError(choice_index)
    item.answered_index = choice_index
    item.answered_at = now
    if choice_index == item.correct_index:
        await progress.record_success(session, user_id=user_id, topic_code=item.topic_code, now=now)
    else:
        await progress.record_mistake(
            session,
            user_id=user_id,
            topic_code=item.topic_code,
            error_type=_parse_error_type(choice_at(item, choice_index).get("error_type"))
            or ErrorType.OTHER,
            now=now,
            quiz_item_id=item.id,
            detail={"quiz_id": quiz_id, "choice_index": choice_index},
        )
    await session.flush()
    if all(other.answered_index is not None for other in quiz.items):
        quiz.status = QuizStatus.COMPLETED
        quiz.completed_at = now
        await session.flush()
    return AnswerResult(item, quiz, choice_index, already_answered=False)
