from collections.abc import Sequence

from yasno.bot.context import BotContext
from yasno.db.models import User
from yasno.max import keyboard
from yasno.max import types as max_types
from yasno.users import upsert_user

type Rows = Sequence[Sequence[keyboard.Button]]


async def ensure_user(ctx: BotContext, actor: max_types.User) -> User:
    async with ctx.sessions.begin() as session:
        return await upsert_user(session, actor)


async def reply(
    ctx: BotContext, user_id: int, text: str, rows: Rows | None = None
) -> max_types.Message:
    while len(text) > 4000:
        split = text.rfind("\n", 0, 4000) + 1
        if split < 2000:
            split = 4000
        await ctx.max.send_message(user_id=user_id, text=text[:split])
        text = text[split:]
    attachments = [keyboard.inline_keyboard(rows)] if rows else None
    return await ctx.max.send_message(user_id=user_id, text=text, attachments=attachments)


def open_app_row(ctx: BotContext, text: str, payload: str | None = None) -> list[keyboard.Button]:
    return [keyboard.open_app(text, ctx.bot_username, payload)]


def callback_args(update: max_types.Update) -> list[str]:
    payload = update.callback.payload if update.callback else None
    return (payload or "").split(":")[1:]
