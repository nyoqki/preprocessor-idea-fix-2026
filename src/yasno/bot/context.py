from dataclasses import dataclass

from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from yasno.config import Settings
from yasno.max.client import MaxClient


@dataclass(slots=True, frozen=True)
class BotContext:
    settings: Settings
    max: MaxClient
    sessions: async_sessionmaker[AsyncSession]
    redis: Redis
    bot_username: str
