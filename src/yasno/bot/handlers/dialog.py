from yasno.ai.exams import looks_like_exam_announcement
from yasno.bot import memory, texts
from yasno.bot.common import callback_args, ensure_user, reply
from yasno.bot.context import BotContext
from yasno.bot.handlers.homework import handle_pending_text
from yasno.bot.handlers.start import continue_onboarding
from yasno.bot.routing import Router, all_of, callback_prefix, has_text, in_dialog
from yasno.clock import local_today
from yasno.db.models import ExamSource, User
from yasno.max import keyboard
from yasno.max.types import Update, UpdateType
from yasno.services import consent, exams, materials

router = Router()

QUESTIONS_PER_DAY = 30


async def _has_consent(ctx: BotContext, user: User) -> bool:
    if consent.has_consent(user):
        return True
    await reply(ctx, user.max_user_id, texts.CONSENT_REQUIRED)
    await continue_onboarding(ctx, user)
    return False


async def _allow_text(ctx: BotContext, user: User) -> bool:
    if not await _has_consent(ctx, user):
        return False
    if not await _within_limit(ctx, user):
        await reply(ctx, user.max_user_id, texts.QUESTION_LIMIT)
        return False
    return True


def is_exam_text(update: Update) -> bool:
    return update.message is not None and looks_like_exam_announcement(update.message.text)


@router.on(UpdateType.MESSAGE_CREATED, all_of(in_dialog, has_text, is_exam_text))
async def on_exam_text(update: Update, ctx: BotContext) -> None:
    assert update.message is not None
    assert update.actor is not None
    user = await ensure_user(ctx, update.actor)
    if not await _allow_text(ctx, user):
        return
    if await handle_pending_text(update, ctx, user):
        return
    today = local_today(ctx.settings.timezone)
    info = await ctx.tutor.extract_exam(update.message.text, today)
    if info is None:
        await _answer_question(update, ctx, user)
        return
    if info.date is None:
        await reply(ctx, user.max_user_id, texts.EXAM_SAVED_NO_DATE.format(title=info.title))
        return
    subject = info.subject or "математика"
    async with ctx.sessions.begin() as session:
        fresh = await session.get(User, user.id, with_for_update=True)
        if fresh is None or not consent.has_consent(fresh):
            return
        exam, _ = await exams.upsert_exam(
            session,
            title=info.title,
            subject=subject,
            scheduled_on=info.date,
            topic_codes=info.topic_codes,
            source=ExamSource.STUDENT,
            user_id=user.id,
            raw_text=update.message.text[:2000],
            source_mid=update.message.body.mid,
        )
    text = texts.EXAM_SAVED.format(
        title=info.title,
        subject=texts.subject_dative(subject),
        when=texts.describe_day(info.date, today),
    )
    rows = [[keyboard.callback(texts.BUTTON_CANCEL, f"exam:del:{exam.id}")]]
    await reply(ctx, user.max_user_id, text, rows)


@router.on(UpdateType.MESSAGE_CALLBACK, callback_prefix("exam"))
async def on_exam_callback(update: Update, ctx: BotContext) -> None:
    assert update.callback is not None
    args = callback_args(update)
    if len(args) != 2 or args[0] != "del" or not args[1].isdigit():
        return
    user = await ensure_user(ctx, update.callback.user)
    async with ctx.sessions.begin() as session:
        deleted = await exams.delete_exam(session, int(args[1]), user)
    await ctx.max.answer_callback(
        update.callback.callback_id,
        text=texts.EXAM_DELETED if deleted else None,
        notification=None if deleted else "Не получилось",
    )


async def _within_limit(ctx: BotContext, user: User) -> bool:
    key = f"questions:{user.id}:{local_today(ctx.settings.timezone).isoformat()}"
    count = await ctx.redis.incr(key)
    if count == 1:
        await ctx.redis.expire(key, 2 * 24 * 3600)
    return int(count) <= QUESTIONS_PER_DAY


async def _answer_question(update: Update, ctx: BotContext, user: User) -> None:
    assert update.message is not None
    await ctx.max.send_action(update.message.chat_id or user.max_user_id)
    context: list[str] = []
    if user.class_id is not None:
        async with ctx.sessions() as session:
            context = await materials.relevant_materials(
                session, user.class_id, update.message.text
            )
    history = await memory.load(ctx, user)
    answer = await ctx.tutor.answer_question(update.message.text, context, user.grade or 9, history)
    await memory.remember_exchange(ctx, user, update.message.text, answer)
    await reply(ctx, user.max_user_id, answer)


@router.on(UpdateType.MESSAGE_CREATED, all_of(in_dialog, has_text))
async def on_text(update: Update, ctx: BotContext) -> None:
    assert update.actor is not None
    if update.actor.is_bot:
        return
    user = await ensure_user(ctx, update.actor)
    if not await _allow_text(ctx, user):
        return
    if await handle_pending_text(update, ctx, user):
        return
    await _answer_question(update, ctx, user)


@router.on(UpdateType.MESSAGE_CREATED, in_dialog)
async def on_other(update: Update, ctx: BotContext) -> None:
    if update.actor is None or update.actor.is_bot:
        return
    await reply(ctx, update.actor.user_id, texts.UNKNOWN_INPUT)
