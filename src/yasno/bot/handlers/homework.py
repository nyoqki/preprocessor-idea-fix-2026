import re

import structlog

from yasno.ai.types import ChatMessage, ProviderError, Role
from yasno.bot import memory, texts
from yasno.bot.common import Rows, callback_args, ensure_user, open_app_row, reply
from yasno.bot.context import BotContext
from yasno.bot.handlers.start import continue_onboarding
from yasno.bot.routing import Router, all_of, callback_prefix, has_image, in_dialog
from yasno.clock import local_today
from yasno.db.models import Submission, User
from yasno.math.topics import topic_title
from yasno.max import keyboard
from yasno.max.client import MaxApiError
from yasno.max.types import Update, UpdateType
from yasno.services import consent
from yasno.services.analysis import (
    Analysis,
    AnalysisDeps,
    Verdict,
    correct_line,
    display,
    evaluate,
    load_transcription,
    start_submission,
    transcribe,
)

log = structlog.get_logger(__name__)

router = Router()

PHOTOS_PER_DAY = 40
STATE_TTL_SECONDS = 3600
FIX_PATTERN = re.compile(r"^\s*(\d{1,2})\s*[:.)]\s*(.+)$", re.DOTALL)


def deps(ctx: BotContext) -> AnalysisDeps:
    return AnalysisDeps(ctx.sessions, ctx.storage, ctx.tutor, ctx.verifier)


def _fix_key(user: User) -> str:
    return f"fix:{user.id}"


def _followup_key(user: User) -> str:
    return f"followup:{user.id}"


async def _within_limit(ctx: BotContext, user: User) -> bool:
    key = f"photos:{user.id}:{local_today(ctx.settings.timezone).isoformat()}"
    count = await ctx.redis.incr(key)
    if count == 1:
        await ctx.redis.expire(key, 2 * 24 * 3600)
    return int(count) <= PHOTOS_PER_DAY


def _review_row(ctx: BotContext, submission_id: int) -> list[keyboard.Button]:
    return open_app_row(ctx, texts.BUTTON_OPEN_REVIEW, f"submission_{submission_id}")


async def present(ctx: BotContext, user: User, analysis: Analysis) -> None:
    submission_id = analysis.submission_id
    rows: Rows = [_review_row(ctx, submission_id)] if submission_id is not None else []
    match analysis.verdict:
        case Verdict.CONFIRM:
            doubtful = {line.index for line in analysis.doubtful}
            listing = "\n".join(
                f"{line.index}{'?' if line.index in doubtful else '.'} {display(line)}"
                for line in analysis.lines
            )
            buttons = [
                keyboard.callback(texts.BUTTON_LINES_OK, f"sub:ok:{submission_id}"),
                keyboard.callback(texts.BUTTON_LINES_FIX, f"sub:fix:{submission_id}"),
            ]
            await reply(ctx, user.max_user_id, texts.CONFIRM_LINES.format(lines=listing), [buttons])
        case Verdict.UNREADABLE:
            await reply(ctx, user.max_user_id, texts.UNREADABLE)
        case Verdict.NOT_MATH:
            await reply(ctx, user.max_user_id, texts.NOT_MATH)
        case Verdict.CORRECT:
            text = (
                texts.VERDICT_CORRECT.format(topic=topic_title(analysis.topic_code))
                if analysis.topic_code
                else texts.VERDICT_CORRECT_NO_TOPIC
            )
            if analysis.topic_code:
                rows = [
                    [keyboard.callback(texts.BUTTON_PRACTICE, f"quiz:topic:{analysis.topic_code}")],
                    *rows,
                ]
            await reply(ctx, user.max_user_id, text, rows)
        case Verdict.ERROR:
            assert analysis.error_line is not None
            assert analysis.hint is not None
            text = texts.VERDICT_ERROR.format(
                index=analysis.error_line.index,
                line=display(analysis.error_line),
                hint=analysis.hint.message,
            )
            await ctx.redis.set(_followup_key(user), str(submission_id), ex=STATE_TTL_SECONDS)
            await memory.remember(ctx, user, ChatMessage(role=Role.ASSISTANT, content=text))
            await reply(ctx, user.max_user_id, text, rows)
        case Verdict.INCOMPLETE:
            await reply(ctx, user.max_user_id, texts.VERDICT_INCOMPLETE, rows)
        case _:
            message = analysis.hint.message if analysis.hint else texts.UNREADABLE
            await reply(ctx, user.max_user_id, message, rows)


async def _evaluate_and_present(ctx: BotContext, user: User, submission_id: int) -> None:
    try:
        analysis = await evaluate(
            deps(ctx), submission_id=submission_id, user_id=user.id, grade=user.grade or 9
        )
    except ProviderError as exc:
        log.warning("evaluation_failed", submission_id=submission_id, error=str(exc))
        await reply(ctx, user.max_user_id, texts.AI_UNAVAILABLE)
        return
    await present(ctx, user, analysis)


@router.on(UpdateType.MESSAGE_CREATED, all_of(in_dialog, has_image))
async def on_photo(update: Update, ctx: BotContext) -> None:
    assert update.message is not None
    assert update.actor is not None
    user = await ensure_user(ctx, update.actor)
    if not consent.has_consent(user):
        await reply(ctx, user.max_user_id, texts.CONSENT_REQUIRED)
        await continue_onboarding(ctx, user)
        return
    if not await _within_limit(ctx, user):
        await reply(ctx, user.max_user_id, texts.PHOTO_LIMIT)
        return
    image_url = next(a.url for a in update.message.all_attachments() if a.type == "image" and a.url)
    await reply(ctx, user.max_user_id, texts.ANALYZING)
    try:
        image = await ctx.max.download(image_url)
    except MaxApiError as exc:
        log.warning("photo_download_failed", error=str(exc))
        await reply(ctx, user.max_user_id, texts.UNSUPPORTED_IMAGE)
        return
    submission, content_type = await start_submission(
        deps(ctx), user_id=user.id, image=image, source_mid=update.message.body.mid
    )
    if submission is None:
        await reply(ctx, user.max_user_id, texts.UNSUPPORTED_IMAGE)
        return
    if submission.finished_at is not None:
        await reply(
            ctx, user.max_user_id, texts.ALREADY_ANALYZED, [_review_row(ctx, submission.id)]
        )
        return
    await ctx.redis.delete(_followup_key(user), _fix_key(user))
    await memory.forget(ctx, user)
    try:
        analysis = await transcribe(deps(ctx), submission.id, image, content_type)
    except ProviderError as exc:
        log.warning("transcription_failed", submission_id=submission.id, error=str(exc))
        await reply(ctx, user.max_user_id, texts.AI_UNAVAILABLE)
        return
    if analysis.verdict is Verdict.REVIEW:
        await _evaluate_and_present(ctx, user, submission.id)
    else:
        await present(ctx, user, analysis)


async def _owned_submission(ctx: BotContext, user: User, raw_id: str) -> int | None:
    if not raw_id.isdigit():
        return None
    async with ctx.sessions() as session:
        submission = await session.get(Submission, int(raw_id))
    if submission is None or submission.user_id != user.id:
        return None
    return submission.id


@router.on(UpdateType.MESSAGE_CALLBACK, callback_prefix("sub"))
async def on_submission_callback(update: Update, ctx: BotContext) -> None:
    assert update.callback is not None
    args = callback_args(update)
    user = await ensure_user(ctx, update.callback.user)
    submission_id = await _owned_submission(ctx, user, args[1]) if len(args) == 2 else None
    if submission_id is None:
        await ctx.max.answer_callback(update.callback.callback_id, notification="Не найдено")
        return
    if args[0] == "fix":
        await ctx.redis.set(_fix_key(user), str(submission_id), ex=STATE_TTL_SECONDS)
        await ctx.max.answer_callback(update.callback.callback_id, text=texts.FIX_PROMPT)
        return
    await ctx.max.answer_callback(update.callback.callback_id, text=texts.ANALYZING)
    await _evaluate_and_present(ctx, user, submission_id)


async def handle_pending_text(update: Update, ctx: BotContext, user: User) -> bool:
    assert update.message is not None
    text = update.message.text
    fix_target = await ctx.redis.get(_fix_key(user))
    if fix_target is not None:
        match = FIX_PATTERN.match(text)
        if match is None:
            await reply(ctx, user.max_user_id, texts.FIX_FORMAT)
            return True
        submission_id = int(fix_target)
        transcription = await correct_line(
            deps(ctx), submission_id, int(match.group(1)), match.group(2).strip()
        )
        await ctx.redis.delete(_fix_key(user))
        if transcription is None:
            return False
        await _evaluate_and_present(ctx, user, submission_id)
        return True
    followup = await ctx.redis.get(_followup_key(user))
    if followup is None:
        return False
    submission_id = int(followup)
    async with ctx.sessions() as session:
        submission = await session.get(Submission, submission_id)
    stored = await load_transcription(deps(ctx), submission_id)
    if submission is None or stored is None or not isinstance(submission.analysis, dict):
        return False
    context = [
        f"Задача: {stored.task or 'не указана'}",
        "Решение ученика:\n" + "\n".join(f"{line.index}. {line.latex}" for line in stored.lines),
    ]
    history = await memory.load(ctx, user)
    answer = await ctx.tutor.answer_question(text, context, user.grade or 9, history)
    await memory.remember_exchange(ctx, user, text, answer)
    await reply(ctx, user.max_user_id, answer, [_review_row(ctx, submission_id)])
    return True
