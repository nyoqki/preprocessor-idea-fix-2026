from yasno.bot import texts
from yasno.bot.context import BotContext
from yasno.bot.routing import Router, in_dialog
from yasno.max.types import Update, UpdateType
from yasno.users import mark_dialog_unavailable, upsert_user

router = Router()


@router.on(UpdateType.BOT_STARTED)
async def on_bot_started(update: Update, ctx: BotContext) -> None:
    actor = update.actor
    if actor is None:
        return
    async with ctx.sessions.begin() as session:
        await upsert_user(session, actor)
    await ctx.max.send_message(
        user_id=actor.user_id, text=texts.GREETING.format(name=actor.first_name or "друг")
    )


@router.on(UpdateType.BOT_STOPPED)
async def on_bot_stopped(update: Update, ctx: BotContext) -> None:
    if update.actor_id is None:
        return
    async with ctx.sessions.begin() as session:
        await mark_dialog_unavailable(session, update.actor_id)


@router.on(UpdateType.MESSAGE_CREATED, in_dialog)
async def on_unknown_message(update: Update, ctx: BotContext) -> None:
    actor = update.actor
    if actor is None or actor.is_bot:
        return
    async with ctx.sessions.begin() as session:
        await upsert_user(session, actor)
    await ctx.max.send_message(user_id=actor.user_id, text=texts.UNKNOWN_INPUT)
