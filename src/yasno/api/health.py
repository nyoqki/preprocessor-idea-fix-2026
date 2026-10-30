from typing import Annotated

from arq import ArqRedis
from fastapi import APIRouter, Depends, Response, status
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from yasno.api.deps import get_queue, get_session

router = APIRouter()


@router.get("/healthz")
async def liveness() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/readyz")
async def readiness(
    response: Response,
    session: Annotated[AsyncSession, Depends(get_session)],
    queue: Annotated[ArqRedis, Depends(get_queue)],
) -> dict[str, str]:
    checks: dict[str, str] = {}
    try:
        await session.execute(text("SELECT 1"))
        checks["database"] = "ok"
    except Exception:
        checks["database"] = "error"
    try:
        await queue.ping()
        checks["redis"] = "ok"
    except Exception:
        checks["redis"] = "error"
    if any(v != "ok" for v in checks.values()):
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return checks
