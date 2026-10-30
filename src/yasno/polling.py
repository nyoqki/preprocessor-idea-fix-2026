import asyncio

import structlog

from yasno.config import Settings
from yasno.max.client import MaxApiError, MaxClient
from yasno.queue import create_queue, enqueue_update

log = structlog.get_logger(__name__)


async def run_polling(settings: Settings, stop: asyncio.Event | None = None) -> None:
    stop = stop or asyncio.Event()
    queue = await create_queue(str(settings.redis_url))
    async with MaxClient(
        settings.max_bot_token.get_secret_value(),
        base_url=str(settings.max_api_url).rstrip("/"),
    ) as client:
        subscriptions = await client.get_subscriptions()
        for subscription in subscriptions.subscriptions:
            log.warning("removing_webhook_for_polling", url=subscription.url)
            await client.unsubscribe(subscription.url)
        marker: int | None = None
        log.info("polling_started")
        try:
            while not stop.is_set():
                try:
                    batch = await client.get_updates(marker=marker, wait_seconds=30)
                except MaxApiError as exc:
                    log.warning("polling_error", error=str(exc))
                    await asyncio.sleep(3)
                    continue
                for update in batch.updates:
                    raw = update.model_dump(mode="json", exclude_none=True)
                    await enqueue_update(queue, raw, update)
                if batch.marker is not None:
                    marker = batch.marker
        finally:
            await queue.aclose()
