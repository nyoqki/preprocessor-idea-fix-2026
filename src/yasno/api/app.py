from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from yasno.api import health, webapp, webhook
from yasno.api.webapp.spa import SecurityHeadersMiddleware, spa_router
from yasno.config import Settings, get_settings
from yasno.db.session import create_engine, create_sessionmaker
from yasno.logs import configure_logging
from yasno.queue import create_queue
from yasno.storage import create_storage


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    configure_logging(settings.log_level, json=settings.log_json)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncGenerator[None]:
        engine = create_engine(
            str(settings.database_url),
            pool_size=settings.database_pool_size,
            max_overflow=settings.database_max_overflow,
        )
        queue = await create_queue(str(settings.redis_url))
        app.state.settings = settings
        app.state.engine = engine
        app.state.sessions = create_sessionmaker(engine)
        app.state.queue = queue
        app.state.storage = create_storage(settings)
        try:
            yield
        finally:
            await queue.aclose()
            await engine.dispose()

    app = FastAPI(
        title="Yasno",
        lifespan=lifespan,
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )
    app.state.settings = settings
    app.add_middleware(SecurityHeadersMiddleware)
    app.include_router(health.router)
    app.include_router(webhook.router)
    app.include_router(webapp.router)
    spa = spa_router(settings.webapp_dist_dir)
    if spa is not None:
        app.include_router(spa)
    return app
