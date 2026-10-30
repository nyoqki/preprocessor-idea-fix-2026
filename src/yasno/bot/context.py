from dataclasses import dataclass

from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from yasno.ai.tutor import Tutor
from yasno.config import Settings
from yasno.max.client import MaxClient
from yasno.services.analysis import Verifier
from yasno.storage import Storage


@dataclass(slots=True, frozen=True)
class BotContext:
    settings: Settings
    max: MaxClient
    sessions: async_sessionmaker[AsyncSession]
    redis: Redis
    tutor: Tutor
    storage: Storage
    verifier: Verifier
    bot_username: str
