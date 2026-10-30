from collections import Counter, defaultdict

from fastapi import APIRouter
from sqlalchemy import func, select

from yasno.api.webapp.auth import CurrentUser
from yasno.api.webapp.common import Session, error_title
from yasno.api.webapp.schemas import (
    ClassOut,
    ErrorTypeCount,
    GapMapOut,
    GapSummary,
    MeOut,
    TopicGapOut,
)
from yasno.db.models import Mistake, SchoolClass
from yasno.services.progress import GapStatus, gap_map

router = APIRouter()


@router.get("/me")
async def me(user: CurrentUser, session: Session) -> MeOut:
    school_class = None
    if user.class_id is not None:
        found = await session.get(SchoolClass, user.class_id)
        if found is not None:
            school_class = ClassOut(id=found.id, title=found.title, grade=found.grade)
    return MeOut(
        id=user.id,
        first_name=user.first_name,
        last_name=user.last_name,
        role=user.role,
        grade=user.grade,
        consent_status=user.consent_status,
        school_class=school_class,
    )


@router.get("/gaps")
async def gaps(user: CurrentUser, session: Session) -> GapMapOut:
    topics = await gap_map(session, user.id)
    rows = await session.execute(
        select(Mistake.topic_code, Mistake.error_type, func.count())
        .where(Mistake.user_id == user.id)
        .group_by(Mistake.topic_code, Mistake.error_type)
    )
    counts: dict[str, list[ErrorTypeCount]] = defaultdict(list)
    for topic_code, error_type, count in rows:
        counts[topic_code].append(
            ErrorTypeCount(
                code=error_type, title=error_title(error_type) or error_type, count=count
            )
        )
    statuses = Counter(topic.status for topic in topics)
    summary = GapSummary(
        weak=statuses[GapStatus.WEAK],
        improving=statuses[GapStatus.IMPROVING],
        solid=statuses[GapStatus.SOLID],
    )
    result = [
        TopicGapOut(
            code=topic.code,
            title=topic.title,
            status=topic.status,
            mistakes_total=topic.mistakes_total,
            correct_total=topic.correct_total,
            last_mistake_at=topic.last_mistake_at,
            next_review_at=topic.next_review_at,
            error_types=sorted(counts[topic.code], key=lambda c: (-c.count, c.title)),
        )
        for topic in topics
    ]
    return GapMapOut(topics=result, summary=summary)
