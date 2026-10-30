from datetime import date

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from yasno.db.models import Exam, ExamSource, User

SUBJECT_TITLES = {
    "algebra": "алгебре",
    "geometry": "геометрии",
    "math": "математике",
    "physics": "физике",
}


def subject_phrase(subject: str) -> str:
    return SUBJECT_TITLES.get(subject, subject)


async def upsert_exam(
    session: AsyncSession,
    *,
    title: str,
    subject: str,
    scheduled_on: date,
    topic_codes: list[str],
    source: ExamSource,
    class_id: int | None = None,
    user_id: int | None = None,
    raw_text: str | None = None,
    source_mid: str | None = None,
) -> tuple[Exam, bool]:
    if class_id is None and user_id is None:
        raise ValueError("exam needs an owner")
    owner = Exam.class_id == class_id if class_id is not None else Exam.user_id == user_id
    result = await session.execute(
        select(Exam).where(owner, Exam.subject == subject, Exam.scheduled_on == scheduled_on)
    )
    existing = result.scalar_one_or_none()
    if existing is not None:
        merged = sorted(set(existing.topic_codes) | set(topic_codes))
        if merged != existing.topic_codes:
            existing.topic_codes = merged
        return existing, False
    exam = Exam(
        title=title[:300],
        subject=subject,
        scheduled_on=scheduled_on,
        topic_codes=sorted(set(topic_codes)),
        source=source,
        class_id=class_id,
        user_id=user_id if class_id is None else None,
        raw_text=raw_text,
        source_mid=source_mid,
    )
    session.add(exam)
    await session.flush()
    return exam, True


async def upcoming_for_user(session: AsyncSession, user: User, today: date) -> list[Exam]:
    owners = [Exam.user_id == user.id]
    if user.class_id is not None:
        owners.append(Exam.class_id == user.class_id)
    result = await session.execute(
        select(Exam)
        .where(or_(*owners), Exam.scheduled_on >= today)
        .order_by(Exam.scheduled_on)
        .limit(10)
    )
    return list(result.scalars())


async def exams_on(session: AsyncSession, day: date) -> list[Exam]:
    result = await session.execute(select(Exam).where(Exam.scheduled_on == day))
    return list(result.scalars())


async def delete_exam(session: AsyncSession, exam_id: int, user: User) -> bool:
    exam = await session.get(Exam, exam_id)
    if exam is None:
        return False
    owns = exam.user_id == user.id or (
        exam.class_id is not None
        and exam.class_id == user.class_id
        and exam.source is ExamSource.STUDENT
    )
    if not owns:
        return False
    await session.delete(exam)
    return True
