from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import ORJSONResponse

from yasno.api import health, webhook
from yasno.config import Settings, get_settings
from yasno.db.session import create_engine, create_sessionmaker
from yasno.logs import configure_logging
from yasno.queue import create_queue


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    configure_logging(settings.log_level, json=settings.log_json)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncGenerator[None]:
        engine = create_engine(str(settings.database_url))
        queue = await create_queue(str(settings.redis_url))
        app.state.settings = settings
        app.state.engine = engine
        app.state.sessions = create_sessionmaker(engine)
        app.state.queue = queue
        try:
            yield
        finally:
            await queue.aclose()
            await engine.dispose()

    app = FastAPI(
        title="Yasno",
        lifespan=lifespan,
        default_response_class=ORJSONResponse,
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )
    app.include_router(health.router)
    app.include_router(webhook.router)
    return app
