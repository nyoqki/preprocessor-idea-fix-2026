import hmac
from typing import Annotated, Any

import orjson
import structlog
from arq import ArqRedis
from fastapi import APIRouter, Depends, Header, HTTPException, Request, Response, status
from pydantic import ValidationError
from redis.exceptions import RedisError

from yasno.api.deps import get_queue, get_settings_dep
from yasno.config import Environment, Settings
from yasno.max.types import Update
from yasno.queue import enqueue_update

log = structlog.get_logger(__name__)

router = APIRouter()


def verify_secret(
    settings: Annotated[Settings, Depends(get_settings_dep)],
    secret: Annotated[str | None, Header(alias="X-Max-Bot-Api-Secret")] = None,
) -> None:
    expected = settings.max_webhook_secret
    if expected is None or not expected.get_secret_value():
        if settings.environment is Environment.PRODUCTION:
            raise HTTPException(
                status.HTTP_503_SERVICE_UNAVAILABLE, detail="webhook_not_configured"
            )
        return
    if secret is None or not hmac.compare_digest(
        secret.encode(), expected.get_secret_value().encode()
    ):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED)


@router.post("/webhook/max", dependencies=[Depends(verify_secret)])
async def receive_update(
    request: Request, queue: Annotated[ArqRedis, Depends(get_queue)]
) -> Response:
    chunks: list[bytes] = []
    size = 0
    async for chunk in request.stream():
        size += len(chunk)
        if size > 1024 * 1024:
            raise HTTPException(status.HTTP_413_CONTENT_TOO_LARGE)
        chunks.append(chunk)
    body = b"".join(chunks)
    try:
        raw: Any = orjson.loads(body)
        update = Update.model_validate(raw)
    except (orjson.JSONDecodeError, ValidationError):
        log.warning("webhook_payload_rejected", size=len(body))
        return Response(status_code=status.HTTP_200_OK)
    try:
        await enqueue_update(queue, raw, update)
    except (RedisError, OSError) as exc:
        log.error("webhook_enqueue_failed", error=str(exc))
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE) from exc
    return Response(status_code=status.HTTP_200_OK)
