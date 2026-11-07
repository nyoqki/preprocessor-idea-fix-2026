from datetime import timedelta
from typing import Any

import structlog
from sqlalchemy import func, select

from yasno.bot import texts
from yasno.bot.common import reply
from yasno.bot.context import BotContext
from yasno.clock import local_now, utcnow
from yasno.db.models import ConsentStatus, Exam, Role, SchoolClass, TopicProgress, User
from yasno.math.topics import topic_title
from yasno.max import keyboard
from yasno.max.client import MaxApiError
from yasno.services import notifications, progress
from yasno.services.access import is_chat_admin

log = structlog.get_logger(__name__)

ACTIVE_HOURS = range(8, 21)
EXAM_LEAD_DAYS = (1, 2)


async def _recipients(ctx: BotContext, exam: Exam) -> list[User]:
    async with ctx.sessions() as session:
        query = select(User).where(
            User.consent_status == ConsentStatus.GRANTED,
            User.dialog_available.is_(True),
            User.role == Role.STUDENT,
        )
        if exam.class_id is not None:
            query = query.where(User.class_id == exam.class_id)
        else:
            query = query.where(User.id == exam.user_id)
        return list((await session.execute(query)).scalars())


async def _notify(
    ctx: BotContext, user: User, kind: str, ref: str, text: str, rows: list[list[Any]]
) -> bool:
    async with ctx.sessions.begin() as session:
        fresh = await session.get(User, user.id, with_for_update=True)
        if (
            fresh is None
            or not fresh.dialog_available
            or fresh.consent_status is ConsentStatus.REVOKED
        ):
            return False
        if fresh.role is Role.STUDENT and fresh.consent_status is not ConsentStatus.GRANTED:
            return False
        claimed = await notifications.claim(session, user.id, kind, ref)
    if claimed is None:
        return False
    try:
        await reply(ctx, user.max_user_id, text, rows)
    except MaxApiError as exc:
        log.warning("reminder_failed", user_id=user.id, kind=kind, error=str(exc))
        async with ctx.sessions.begin() as session:
            await notifications.release_failed(session, claimed)
        return False
    async with ctx.sessions.begin() as session:
        await notifications.mark_sent(session, claimed)
    return True


async def send_exam_reminders(job_ctx: dict[str, Any]) -> int:
    ctx: BotContext = job_ctx["bot"]
    now = local_now(ctx.settings.timezone)
    if now.hour not in ACTIVE_HOURS:
        return 0
    today = now.date()
    days = [today + timedelta(days=d) for d in EXAM_LEAD_DAYS]
    async with ctx.sessions() as session:
        upcoming = list(
            (await session.execute(select(Exam).where(Exam.scheduled_on.in_(days)))).scalars()
        )
    sent = 0
    for exam in upcoming:
        topics = ", ".join(topic_title(code) for code in exam.topic_codes[:3])
        text = texts.EXAM_REMINDER.format(
            when="Завтра" if exam.scheduled_on == days[0] else "Послезавтра",
            title=exam.title.lower(),
            subject=texts.subject_dative(exam.subject),
            topics=f" ({topics})" if topics else "",
        )
        rows = [
            [
                keyboard.callback(texts.BUTTON_START_QUIZ, f"quiz:exam:{exam.id}"),
                keyboard.callback(texts.BUTTON_LATER, "quiz:later"),
            ]
        ]
        for user in await _recipients(ctx, exam):
            sent += await _notify(ctx, user, "exam", str(exam.id), text, rows)
    log.info("exam_reminders_sent", count=sent)
    return sent


async def send_review_reminders(job_ctx: dict[str, Any]) -> int:
    ctx: BotContext = job_ctx["bot"]
    today = local_now(ctx.settings.timezone).date().isoformat()
    async with ctx.sessions() as session:
        due = await progress.due_reviews(session, now=utcnow())
        user_ids = {p.user_id for p in due}
        users = {
            u.id: u
            for u in (
                await session.execute(
                    select(User).where(
                        User.id.in_(user_ids),
                        User.consent_status == ConsentStatus.GRANTED,
                        User.dialog_available.is_(True),
                    )
                )
            ).scalars()
        }
    chosen: dict[int, str] = {}
    for item in due:
        if item.user_id in users and item.user_id not in chosen:
            chosen[item.user_id] = item.topic_code
    sent = 0
    for user_id, topic in chosen.items():
        text = texts.REVIEW_REMINDER.format(topic=topic_title(topic))
        rows = [
            [
                keyboard.callback(texts.BUTTON_START_QUIZ, f"quiz:review:{topic}"),
                keyboard.callback(texts.BUTTON_LATER, "quiz:later"),
            ]
        ]
        sent += await _notify(ctx, users[user_id], "review", today, text, rows)
    log.info("review_reminders_sent", count=sent)
    return sent


MIN_GROUP_FOR_DIGEST = 2


async def _class_digest(ctx: BotContext, class_id: int) -> str | None:
    async with ctx.sessions() as session:
        total = await session.scalar(
            select(func.count())
            .select_from(User)
            .where(User.class_id == class_id, User.role == Role.STUDENT)
        )
        rows = (
            await session.execute(
                select(TopicProgress.topic_code, func.count(TopicProgress.user_id))
                .join(User, User.id == TopicProgress.user_id)
                .where(
                    User.class_id == class_id,
                    User.role == Role.STUDENT,
                    TopicProgress.mistakes_total > 0,
                    TopicProgress.box <= 1,
                )
                .group_by(TopicProgress.topic_code)
                .having(func.count(TopicProgress.user_id) >= MIN_GROUP_FOR_DIGEST)
                .order_by(func.count(TopicProgress.user_id).desc())
                .limit(5)
            )
        ).all()
    if not rows:
        return None
    lines = [f"• {topic_title(code)} — {count} из {total}" for code, count in rows]
    return texts.TEACHER_DIGEST.format(topics="\n".join(lines))


async def send_teacher_digest(job_ctx: dict[str, Any]) -> int:
    ctx: BotContext = job_ctx["bot"]
    week = local_now(ctx.settings.timezone).strftime("%G-W%V")
    async with ctx.sessions() as session:
        teachers = list(
            (
                await session.execute(
                    select(User).where(
                        User.role == Role.TEACHER,
                        User.class_id.is_not(None),
                        User.dialog_available.is_(True),
                    )
                )
            ).scalars()
        )
    sent = 0
    digests: dict[int, str | None] = {}
    for teacher in teachers:
        assert teacher.class_id is not None
        async with ctx.sessions() as session:
            school_class = await session.get(SchoolClass, teacher.class_id)
        if school_class is None or not await is_chat_admin(
            ctx.max, school_class.max_chat_id, teacher.max_user_id
        ):
            continue
        if teacher.class_id not in digests:
            digests[teacher.class_id] = await _class_digest(ctx, teacher.class_id)
        digest = digests[teacher.class_id]
        if digest is None:
            continue
        rows = [[keyboard.open_app(texts.BUTTON_OPEN_TEACHER, ctx.bot_username, "teacher")]]
        sent += await _notify(ctx, teacher, "teacher_digest", week, digest, rows)
    log.info("teacher_digests_sent", count=sent)
    return sent
