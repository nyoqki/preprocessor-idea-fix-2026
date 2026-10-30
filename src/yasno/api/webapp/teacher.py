from collections import Counter, defaultdict

from fastapi import APIRouter
from sqlalchemy import func, select

from yasno.api.webapp.auth import Teacher
from yasno.api.webapp.common import Session, error_title
from yasno.api.webapp.schemas import (
    ClassOut,
    ErrorTypeCount,
    TeacherSummaryOut,
    TeacherTopicOut,
)
from yasno.db.models import Mistake, Role, SchoolClass, TopicProgress, User
from yasno.math.topics import topic_title
from yasno.services.progress import GapStatus, status_for

router = APIRouter(prefix="/teacher")


@router.get("/summary")
async def class_summary(teacher: Teacher, session: Session) -> TeacherSummaryOut:
    school_class = (
        await session.get(SchoolClass, teacher.class_id) if teacher.class_id is not None else None
    )
    if school_class is None:
        return TeacherSummaryOut(
            school_class=None, students_total=0, students_with_gaps=0, topics=[]
        )
    in_class = (User.class_id == school_class.id, User.role == Role.STUDENT)
    students_total = await session.scalar(select(func.count()).select_from(User).where(*in_class))
    progress = await session.execute(
        select(TopicProgress)
        .join(User, User.id == TopicProgress.user_id)
        .where(*in_class, TopicProgress.mistakes_total > 0)
    )
    statuses: dict[str, Counter[GapStatus]] = defaultdict(Counter)
    struggling: set[int] = set()
    for row in progress.scalars():
        gap_status = status_for(row)
        statuses[row.topic_code][gap_status] += 1
        if gap_status is not GapStatus.SOLID:
            struggling.add(row.user_id)
    errors = await session.execute(
        select(Mistake.topic_code, Mistake.error_type, func.count())
        .join(User, User.id == Mistake.user_id)
        .where(*in_class)
        .group_by(Mistake.topic_code, Mistake.error_type)
    )
    top_errors: dict[str, ErrorTypeCount] = {}
    for topic_code, error_type, count in errors:
        current = top_errors.get(topic_code)
        if current is None or count > current.count:
            top_errors[topic_code] = ErrorTypeCount(
                code=error_type, title=error_title(error_type) or error_type, count=count
            )
    topics = [
        TeacherTopicOut(
            code=code,
            title=topic_title(code),
            weak=counts[GapStatus.WEAK],
            improving=counts[GapStatus.IMPROVING],
            solid=counts[GapStatus.SOLID],
            top_error_type=top_errors.get(code),
        )
        for code, counts in statuses.items()
    ]
    topics.sort(key=lambda t: (-t.weak, -t.improving, t.title))
    return TeacherSummaryOut(
        school_class=ClassOut(
            id=school_class.id, title=school_class.title, grade=school_class.grade
        ),
        students_total=students_total or 0,
        students_with_gaps=len(struggling),
        topics=topics,
    )
