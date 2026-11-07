from collections.abc import AsyncIterator
from typing import Annotated

from arq import ArqRedis
from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from yasno.config import Settings
from yasno.max.client import MaxClient
from yasno.max.tls import build_ssl_context


def get_settings_dep(request: Request) -> Settings:
    settings: Settings = request.app.state.settings
    return settings


def get_queue(request: Request) -> ArqRedis:
    queue: ArqRedis = request.app.state.queue
    return queue


async def get_session(request: Request) -> AsyncIterator[AsyncSession]:
    sessions: async_sessionmaker[AsyncSession] = request.app.state.sessions
    async with sessions() as session:
        yield session


async def get_max_client(
    settings: Annotated[Settings, Depends(get_settings_dep)],
) -> AsyncIterator[MaxClient]:
    async with MaxClient(
        settings.max_bot_token.get_secret_value(),
        base_url=str(settings.max_api_url).rstrip("/"),
        verify=build_ssl_context(settings.max_extra_ca_file),
        timeout=4.0,
        max_retries=0,
    ) as client:
        yield client
