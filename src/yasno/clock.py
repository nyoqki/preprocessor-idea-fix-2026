from datetime import UTC, date, datetime
from functools import lru_cache
from zoneinfo import ZoneInfo


@lru_cache
def zone(name: str) -> ZoneInfo:
    return ZoneInfo(name)


def utcnow() -> datetime:
    return datetime.now(UTC)


def local_now(tz: str) -> datetime:
    return datetime.now(zone(tz))


def local_today(tz: str) -> date:
    return local_now(tz).date()
