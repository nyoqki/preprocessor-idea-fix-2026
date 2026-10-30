import hmac
from typing import Annotated, Any

import orjson
import structlog
from arq import ArqRedis
from fastapi import APIRouter, Depends, Header, HTTPException, Request, Response, status
from pydantic import ValidationError
from redis.exceptions import RedisError

from yasno.api.deps import get_queue, get_settings_dep
from yasno.config import Settings
from yasno.max.types import Update
from yasno.queue import enqueue_update

log = structlog.get_logger(__name__)

router = APIRouter()


def verify_secret(
    settings: Annotated[Settings, Depends(get_settings_dep)],
    secret: Annotated[str | None, Header(alias="X-Max-Bot-Api-Secret")] = None,
) -> None:
    expected = settings.max_webhook_secret
    if expected is None:
        return
    if secret is None or not hmac.compare_digest(secret, expected.get_secret_value()):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED)


@router.post("/webhook/max", dependencies=[Depends(verify_secret)])
async def receive_update(
    request: Request, queue: Annotated[ArqRedis, Depends(get_queue)]
) -> Response:
    body = await request.body()
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
