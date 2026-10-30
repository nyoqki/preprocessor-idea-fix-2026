from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from yasno.db.models import Mistake, TopicProgress
from yasno.math.errors import ErrorType
from yasno.math.topics import topic_title

REVIEW_INTERVALS = (timedelta(days=2), timedelta(days=4), timedelta(days=7), timedelta(days=14))
MAX_BOX = len(REVIEW_INTERVALS)


class GapStatus(StrEnum):
    WEAK = "weak"
    IMPROVING = "improving"
    SOLID = "solid"


@dataclass(frozen=True, slots=True)
class TopicGap:
    code: str
    title: str
    status: GapStatus
    mistakes_total: int
    correct_total: int
    last_mistake_at: datetime | None
    next_review_at: datetime | None


def schedule(box: int, *, correct: bool, now: datetime) -> tuple[int, datetime | None]:
    if not correct:
        return 0, now + REVIEW_INTERVALS[0]
    new_box = min(box + 1, MAX_BOX)
    if new_box >= MAX_BOX:
        return new_box, None
    return new_box, now + REVIEW_INTERVALS[new_box]


def status_for(progress: TopicProgress) -> GapStatus:
    if progress.mistakes_total == 0 or progress.box >= MAX_BOX:
        return GapStatus.SOLID
    if progress.box <= 1:
        return GapStatus.WEAK
    return GapStatus.IMPROVING


async def _locked(session: AsyncSession, user_id: int, topic_code: str) -> TopicProgress:
    await session.execute(
        insert(TopicProgress)
        .values(user_id=user_id, topic_code=topic_code)
        .on_conflict_do_nothing(index_elements=[TopicProgress.user_id, TopicProgress.topic_code])
    )
    result = await session.execute(
        select(TopicProgress)
        .where(TopicProgress.user_id == user_id, TopicProgress.topic_code == topic_code)
        .with_for_update()
    )
    return result.scalar_one()


async def record_mistake(
    session: AsyncSession,
    *,
    user_id: int,
    topic_code: str,
    error_type: ErrorType,
    now: datetime,
    submission_id: int | None = None,
    quiz_item_id: int | None = None,
    step_index: int | None = None,
    detail: dict[str, object] | None = None,
) -> Mistake:
    progress = await _locked(session, user_id, topic_code)
    progress.box, progress.next_review_at = schedule(progress.box, correct=False, now=now)
    progress.mistakes_total += 1
    progress.last_mistake_at = now
    mistake = Mistake(
        user_id=user_id,
        topic_code=topic_code,
        error_type=error_type.value,
        submission_id=submission_id,
        quiz_item_id=quiz_item_id,
        step_index=step_index,
        detail=detail,
    )
    session.add(mistake)
    await session.flush()
    return mistake


async def record_success(
    session: AsyncSession, *, user_id: int, topic_code: str, now: datetime
) -> TopicProgress:
    progress = await _locked(session, user_id, topic_code)
    progress.box, progress.next_review_at = schedule(progress.box, correct=True, now=now)
    progress.correct_total += 1
    progress.last_practice_at = now
    return progress


async def gap_map(session: AsyncSession, user_id: int) -> list[TopicGap]:
    result = await session.execute(
        select(TopicProgress).where(
            TopicProgress.user_id == user_id, TopicProgress.mistakes_total > 0
        )
    )
    gaps = [
        TopicGap(
            code=p.topic_code,
            title=topic_title(p.topic_code),
            status=status_for(p),
            mistakes_total=p.mistakes_total,
            correct_total=p.correct_total,
            last_mistake_at=p.last_mistake_at,
            next_review_at=p.next_review_at,
        )
        for p in result.scalars()
    ]
    order = {GapStatus.WEAK: 0, GapStatus.IMPROVING: 1, GapStatus.SOLID: 2}
    return sorted(gaps, key=lambda g: (order[g.status], -g.mistakes_total, g.title))


async def weakest_topics(session: AsyncSession, user_id: int, limit: int = 3) -> list[str]:
    return [g.code for g in await gap_map(session, user_id) if g.status is not GapStatus.SOLID][
        :limit
    ]


async def due_reviews(
    session: AsyncSession, *, now: datetime, limit: int = 500
) -> list[TopicProgress]:
    result = await session.execute(
        select(TopicProgress)
        .where(TopicProgress.next_review_at.is_not(None), TopicProgress.next_review_at <= now)
        .order_by(TopicProgress.next_review_at)
        .limit(limit)
    )
    return list(result.scalars())
