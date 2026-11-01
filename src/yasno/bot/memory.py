import orjson
from pydantic import ValidationError

from yasno.ai.types import ChatMessage, Role
from yasno.bot.context import BotContext
from yasno.db.models import User

HISTORY_TTL_SECONDS = 30 * 60
HISTORY_MESSAGES = 8
MESSAGE_CHARS = 1500


def _key(user: User) -> str:
    return f"history:{user.id}"


async def load(ctx: BotContext, user: User) -> list[ChatMessage]:
    raw = await ctx.redis.get(_key(user))
    if raw is None:
        return []
    try:
        items = orjson.loads(raw)
        return [ChatMessage.model_validate(item) for item in items]
    except (orjson.JSONDecodeError, ValidationError, TypeError):
        return []


async def remember(ctx: BotContext, user: User, *messages: ChatMessage) -> None:
    history = [*await load(ctx, user), *messages][-HISTORY_MESSAGES:]
    payload = [
        {"role": item.role.value, "content": item.content[:MESSAGE_CHARS]} for item in history
    ]
    await ctx.redis.set(_key(user), orjson.dumps(payload).decode(), ex=HISTORY_TTL_SECONDS)


async def remember_exchange(ctx: BotContext, user: User, question: str, answer: str) -> None:
    await remember(
        ctx,
        user,
        ChatMessage(role=Role.USER, content=question),
        ChatMessage(role=Role.ASSISTANT, content=answer),
    )


async def forget(ctx: BotContext, user: User) -> None:
    await ctx.redis.delete(_key(user))
