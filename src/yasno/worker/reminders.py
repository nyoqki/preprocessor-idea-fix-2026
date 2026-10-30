from datetime import timedelta
from typing import Any

import structlog
from sqlalchemy import select

from yasno.bot import texts
from yasno.bot.common import reply
from yasno.bot.context import BotContext
from yasno.clock import local_now, utcnow
from yasno.db.models import ConsentStatus, Exam, Role, User
from yasno.math.topics import topic_title
from yasno.max import keyboard
from yasno.max.client import MaxApiError
from yasno.services import notifications, progress

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
        claimed = await notifications.claim(session, user.id, kind, ref)
    if claimed is None:
        return False
    try:
        await reply(ctx, user.max_user_id, text, rows)
    except MaxApiError as exc:
        log.warning("reminder_failed", user_id=user.id, kind=kind, error=str(exc))
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
