import os
from collections.abc import AsyncIterator
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

os.environ.setdefault("MAX_BOT_TOKEN", "test-token")
os.environ.setdefault("ENVIRONMENT", "test")
os.environ.setdefault("LOG_JSON", "false")

from yasno.config import Settings

Settings.model_config["env_file"] = None


@pytest.fixture
async def db_sessions() -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    from yasno.db.base import Base
    from yasno.db.session import create_sessionmaker

    url = os.environ.get("TEST_DATABASE_URL")
    if not url:
        pytest.skip("TEST_DATABASE_URL is not set")
    schema = f"test_{uuid4().hex[:16]}"
    admin = create_async_engine(url)
    async with admin.begin() as conn:
        await conn.execute(text(f'CREATE SCHEMA "{schema}"'))
    engine = create_async_engine(url, connect_args={"server_settings": {"search_path": schema}})
    try:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        yield create_sessionmaker(engine)
    finally:
        await engine.dispose()
        async with admin.begin() as conn:
            await conn.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        await admin.dispose()
