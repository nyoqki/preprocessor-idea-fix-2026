import asyncio

from alembic import context
from sqlalchemy.ext.asyncio import create_async_engine

from yasno.db import models
from yasno.db.base import Base

assert models

target_metadata = Base.metadata


def _configure(connection: object | None = None, url: str | None = None) -> None:
    context.configure(
        connection=connection,  # type: ignore[arg-type]
        url=url,
        target_metadata=target_metadata,
        compare_type=True,
        compare_server_default=True,
        literal_binds=connection is None,
    )


def run_offline() -> None:
    _configure(url=context.config.get_main_option("sqlalchemy.url"))
    with context.begin_transaction():
        context.run_migrations()


def _run_sync(connection: object) -> None:
    _configure(connection=connection)
    with context.begin_transaction():
        context.run_migrations()


async def run_online() -> None:
    url = context.config.get_main_option("sqlalchemy.url")
    assert url is not None
    engine = create_async_engine(url)
    async with engine.connect() as connection:
        await connection.run_sync(_run_sync)
    await engine.dispose()


if context.is_offline_mode():
    run_offline()
else:
    asyncio.run(run_online())
