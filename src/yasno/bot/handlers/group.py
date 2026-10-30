import structlog

from yasno.ai.exams import looks_like_exam_announcement
from yasno.bot import texts
from yasno.bot.context import BotContext
from yasno.bot.links import start_link
from yasno.bot.routing import Router, has_text, in_group
from yasno.clock import local_today
from yasno.db.models import ExamSource
from yasno.max import keyboard
from yasno.max.client import MaxApiError
from yasno.max.types import Update, UpdateType
from yasno.services import classes, exams

log = structlog.get_logger(__name__)

router = Router()

READ_PERMISSION = "read_all_messages"


async def _can_read(ctx: BotContext, chat_id: int) -> bool:
    try:
        membership = await ctx.max.get_my_membership(chat_id)
    except MaxApiError:
        return False
    return membership.is_owner or READ_PERMISSION in (membership.permissions or [])


@router.on(UpdateType.BOT_ADDED)
async def on_bot_added(update: Update, ctx: BotContext) -> None:
    if update.chat_id is None or update.is_channel:
        return
    try:
        title = (await ctx.max.get_chat(update.chat_id)).title
    except MaxApiError:
        title = None
    can_read = await _can_read(ctx, update.chat_id)
    async with ctx.sessions.begin() as session:
        school_class, _ = await classes.ensure_class_for_chat(session, update.chat_id, title)
        school_class.bot_can_read_chat = can_read
        code = school_class.invite_code
    text = texts.CLASS_CONNECTED + ("" if can_read else texts.CLASS_CONNECTED_NO_READ)
    rows = [
        [keyboard.link(texts.BUTTON_JOIN, start_link(ctx.bot_username, f"join_{code}"))],
        [keyboard.link(texts.BUTTON_TEACHER, start_link(ctx.bot_username, f"teach_{code}"))],
    ]
    await ctx.max.send_message(
        chat_id=update.chat_id, text=text, attachments=[keyboard.inline_keyboard(rows)]
    )
    log.info("class_connected", chat_id=update.chat_id, can_read=can_read)


@router.on(UpdateType.BOT_REMOVED)
async def on_bot_removed(update: Update, ctx: BotContext) -> None:
    if update.chat_id is None:
        return
    async with ctx.sessions.begin() as session:
        school_class = await classes.class_for_chat(session, update.chat_id)
        if school_class is not None:
            school_class.bot_can_read_chat = False


@router.on(UpdateType.CHAT_TITLE_CHANGED)
async def on_title_changed(update: Update, ctx: BotContext) -> None:
    if update.chat_id is None:
        return
    async with ctx.sessions.begin() as session:
        school_class = await classes.class_for_chat(session, update.chat_id)
        if school_class is not None and update.title:
            school_class.title = update.title[:200]


@router.on(UpdateType.MESSAGE_CREATED, in_group)
async def on_group_message(update: Update, ctx: BotContext) -> None:
    message = update.message
    if message is None or message.chat_id is None:
        return
    if message.sender is not None and message.sender.is_bot:
        return
    async with ctx.sessions.begin() as session:
        school_class = await classes.class_for_chat(session, message.chat_id)
        if school_class is None:
            return
        if not school_class.bot_can_read_chat:
            school_class.bot_can_read_chat = True
        class_id = school_class.id
    if not has_text(update) or not looks_like_exam_announcement(message.text):
        return
    info = await ctx.tutor.extract_exam(message.text, local_today(ctx.settings.timezone))
    if info is None or info.date is None:
        return
    async with ctx.sessions.begin() as session:
        exam, created = await exams.upsert_exam(
            session,
            title=info.title,
            subject=info.subject or "математика",
            scheduled_on=info.date,
            topic_codes=info.topic_codes,
            source=ExamSource.CHAT,
            class_id=class_id,
            raw_text=message.text[:2000],
            source_mid=message.body.mid,
        )
    log.info("exam_from_chat", exam_id=exam.id, created=created, class_id=class_id)
