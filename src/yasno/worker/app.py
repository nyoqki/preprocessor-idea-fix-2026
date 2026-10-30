from typing import Any, ClassVar, cast

import structlog
from arq import cron
from arq.typing import WorkerCoroutine
from pydantic import ValidationError
from redis.asyncio import Redis

from yasno.ai.registry import build_ai
from yasno.ai.tutor import Tutor
from yasno.bot import texts
from yasno.bot.app import build_router
from yasno.bot.context import BotContext
from yasno.bot.routing import Router
from yasno.config import get_settings
from yasno.db.session import create_engine, create_sessionmaker
from yasno.logs import configure_logging
from yasno.max.client import MaxApiError, MaxClient
from yasno.max.types import Update
from yasno.queue import HANDLE_UPDATE, JOB_RESULT_TTL_SECONDS, QUEUE_NAME, redis_settings
from yasno.storage import LocalStorage
from yasno.worker.reminders import send_exam_reminders, send_review_reminders

log = structlog.get_logger(__name__)

type JobContext = dict[str, Any]


async def startup(job_ctx: JobContext) -> None:
    settings = get_settings()
    configure_logging(settings.log_level, json=settings.log_json)
    max_client = MaxClient(
        settings.max_bot_token.get_secret_value(),
        base_url=str(settings.max_api_url).rstrip("/"),
    )
    engine = create_engine(str(settings.database_url))
    redis = Redis.from_url(str(settings.redis_url))
    ai = build_ai(settings)
    me = await max_client.get_me()
    job_ctx["engine"] = engine
    job_ctx["ai"] = ai
    job_ctx["router"] = build_router()
    job_ctx["bot"] = BotContext(
        settings=settings,
        max=max_client,
        sessions=create_sessionmaker(engine),
        redis=redis,
        tutor=Tutor.from_services(ai),
        storage=LocalStorage(settings.storage_dir),
        bot_username=me.username or "",
    )
    log.info("worker_started", bot=me.username)


async def shutdown(job_ctx: JobContext) -> None:
    bot: BotContext | None = job_ctx.get("bot")
    if bot is not None:
        await bot.max.aclose()
        await bot.redis.aclose()
    ai = job_ctx.get("ai")
    if ai is not None:
        await ai.aclose()
    engine = job_ctx.get("engine")
    if engine is not None:
        await engine.dispose()


async def handle_update(job_ctx: JobContext, raw: dict[str, Any]) -> None:
    try:
        update = Update.model_validate(raw)
    except ValidationError:
        log.exception("update_invalid")
        return
    router: Router = job_ctx["router"]
    bot: BotContext = job_ctx["bot"]
    try:
        await router.dispatch(update, bot)
    except Exception:
        log.exception("update_failed", update_type=update.update_type)
        await _notify_failure(update, bot)


async def _notify_failure(update: Update, bot: BotContext) -> None:
    message = update.message
    user_id = update.actor_id
    if user_id is None or (message is not None and not message.is_dialog):
        return
    try:
        await bot.max.send_message(user_id=user_id, text=texts.INTERNAL_ERROR)
    except MaxApiError:
        log.warning("failure_notice_not_sent", user_id=user_id)


class WorkerSettings:
    functions: ClassVar[list[Any]] = [handle_update]
    cron_jobs: ClassVar[list[Any]] = [
        cron(
            cast(WorkerCoroutine, send_exam_reminders),
            minute={5, 35},
            run_at_startup=False,
            unique=True,
        ),
        cron(cast(WorkerCoroutine, send_review_reminders), hour={13}, minute={0}, unique=True),
    ]
    on_startup = startup
    on_shutdown = shutdown
    queue_name = QUEUE_NAME
    keep_result = JOB_RESULT_TTL_SECONDS
    max_jobs = 20
    job_timeout = 300
    redis_settings = redis_settings(str(get_settings().redis_url))


__all__ = ["HANDLE_UPDATE", "WorkerSettings"]
