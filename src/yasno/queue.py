import hashlib
from typing import Any

from arq import ArqRedis, create_pool
from arq.connections import RedisSettings

from yasno.max.types import Update

HANDLE_UPDATE = "handle_update"
QUEUE_NAME = "yasno:updates"
JOB_RESULT_TTL_SECONDS = 24 * 3600


def redis_settings(url: str) -> RedisSettings:
    return RedisSettings.from_dsn(url)


async def create_queue(url: str) -> ArqRedis:
    return await create_pool(redis_settings(url), default_queue_name=QUEUE_NAME)


def update_job_id(update: Update) -> str:
    digest = hashlib.sha256(update.dedup_key().encode()).hexdigest()[:32]
    return f"upd:{digest}"


async def enqueue_update(queue: ArqRedis, raw: dict[str, Any], update: Update) -> bool:
    job = await queue.enqueue_job(
        HANDLE_UPDATE, raw, _job_id=update_job_id(update), _queue_name=QUEUE_NAME
    )
    return job is not None
