import asyncio
from typing import Any, ClassVar, cast

import structlog
from arq import cron
from arq.typing import WorkerCoroutine
from pydantic import ValidationError
from redis.asyncio import Redis
from sqlalchemy import select

from yasno.ai.registry import build_ai
from yasno.ai.tutor import Tutor
from yasno.bot import texts
from yasno.bot.app import build_router
from yasno.bot.context import BotContext
from yasno.bot.routing import Router
from yasno.config import get_settings
from yasno.db.models import Submission, SubmissionStatus, User
from yasno.db.session import create_engine, create_sessionmaker
from yasno.logs import configure_logging
from yasno.max.client import MaxApiError, MaxClient
from yasno.max.tls import build_ssl_context
from yasno.max.types import Update
from yasno.queue import HANDLE_UPDATE, JOB_RESULT_TTL_SECONDS, QUEUE_NAME, redis_settings
from yasno.services.analysis import AnalysisDeps, Verifier, fail_submission
from yasno.storage import LocalStorage
from yasno.worker.reminders import (
    send_exam_reminders,
    send_review_reminders,
    send_teacher_digest,
)

log = structlog.get_logger(__name__)

type JobContext = dict[str, Any]
UPDATE_TIMEOUT_SECONDS = 240.0


async def startup(job_ctx: JobContext) -> None:
    settings = get_settings()
    configure_logging(settings.log_level, json=settings.log_json)
    max_client = MaxClient(
        settings.max_bot_token.get_secret_value(),
        base_url=str(settings.max_api_url).rstrip("/"),
        verify=build_ssl_context(settings.max_extra_ca_file),
    )
    engine = create_engine(
        str(settings.database_url),
        pool_size=settings.database_pool_size,
        max_overflow=settings.database_max_overflow,
    )
    redis = Redis.from_url(str(settings.redis_url))
    ai = build_ai(settings)
    me = await max_client.get_me()
    try:
        await max_client.set_commands(texts.BOT_COMMANDS)
    except MaxApiError as exc:
        log.warning("bot_commands_not_set", status=exc.status, code=exc.code)
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
        verifier=Verifier(workers=settings.math_workers),
        bot_username=me.username or "",
    )
    log.info("worker_started", bot=me.username)


async def shutdown(job_ctx: JobContext) -> None:
    bot: BotContext | None = job_ctx.get("bot")
    if bot is not None:
        bot.verifier.close()
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
        async with asyncio.timeout(UPDATE_TIMEOUT_SECONDS):
            await router.dispatch(update, bot)
    except Exception:
        log.exception("update_failed", update_type=update.update_type)
        await _fail_processing(update, bot)
        await _notify_failure(update, bot)


async def _fail_processing(update: Update, bot: BotContext) -> None:
    message = update.message
    if message is None or not message.is_dialog or update.actor_id is None:
        return
    try:
        async with bot.sessions() as session:
            ids = list(
                await session.scalars(
                    select(Submission.id)
                    .join(User, User.id == Submission.user_id)
                    .where(
                        User.max_user_id == update.actor_id,
                        Submission.source_mid == message.body.mid,
                        Submission.status == SubmissionStatus.PROCESSING,
                    )
                )
            )
        deps = AnalysisDeps(bot.sessions, bot.storage, bot.tutor, bot.verifier)
        for submission_id in ids:
            await fail_submission(deps, submission_id)
    except Exception:
        log.exception("failed_submission_status_not_saved")


async def _notify_failure(update: Update, bot: BotContext) -> None:
    message = update.message
    user_id = update.actor_id
    if user_id is None or (message is not None and not message.is_dialog):
        return
    try:
        async with asyncio.timeout(10):
            await bot.max.send_message(user_id=user_id, text=texts.INTERNAL_ERROR)
    except (MaxApiError, TimeoutError):
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
        cron(
            cast(WorkerCoroutine, send_teacher_digest),
            weekday={6},
            hour={15},
            minute={0},
            unique=True,
        ),
    ]
    on_startup = startup
    on_shutdown = shutdown
    queue_name = QUEUE_NAME
    keep_result = JOB_RESULT_TTL_SECONDS
    max_jobs = get_settings().worker_max_jobs
    job_timeout = 300
    redis_settings = redis_settings(str(get_settings().redis_url))


__all__ = ["HANDLE_UPDATE", "WorkerSettings"]
