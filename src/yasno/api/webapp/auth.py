import hashlib
import hmac
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Annotated, Any
from urllib.parse import unquote_plus

import orjson
import structlog
from fastapi import Depends, Header, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from yasno.api.deps import get_session, get_settings_dep
from yasno.config import Settings
from yasno.db.models import Role, User
from yasno.max import types as max_types
from yasno.users import upsert_user

log = structlog.get_logger(__name__)

AUTH_SCHEME = "tma"
CLOCK_SKEW = timedelta(minutes=5)
MEDIA_TOKEN_BUCKET_SECONDS = 3600
MEDIA_TOKEN_BUCKETS = 3


class InitDataError(Exception):
    pass


@dataclass(frozen=True, slots=True)
class WebAppUser:
    id: int
    first_name: str
    last_name: str | None
    username: str | None
    language_code: str | None
    photo_url: str | None


@dataclass(frozen=True, slots=True)
class InitData:
    user: WebAppUser
    auth_date: datetime
    query_id: str | None
    start_param: str | None
    chat_id: int | None


def _secret_key(bot_token: str) -> bytes:
    return hmac.new(b"WebAppData", bot_token.encode(), hashlib.sha256).digest()


def data_check_string(pairs: dict[str, str]) -> str:
    return "\n".join(f"{key}={pairs[key]}" for key in sorted(pairs))


def sign_init_data(pairs: dict[str, str], bot_token: str) -> str:
    return hmac.new(
        _secret_key(bot_token), data_check_string(pairs).encode(), hashlib.sha256
    ).hexdigest()


def _split(raw: str) -> tuple[dict[str, str], str]:
    pairs: dict[str, str] = {}
    hashes: list[str] = []
    for chunk in raw.split("&"):
        key, sep, value = chunk.partition("=")
        if not sep or not key:
            raise InitDataError("malformed pair")
        key = unquote_plus(key)
        if key == "hash":
            hashes.append(value)
            continue
        if key in pairs:
            raise InitDataError(f"duplicate key {key}")
        pairs[key] = unquote_plus(value)
    if len(hashes) != 1:
        raise InitDataError("hash must be present exactly once")
    return pairs, hashes[0]


def _optional_str(data: dict[str, Any], key: str) -> str | None:
    value = data.get(key)
    return value if isinstance(value, str) and value else None


def _parse_user(raw: str | None) -> WebAppUser:
    if raw is None:
        raise InitDataError("user is missing")
    try:
        data = orjson.loads(raw)
    except orjson.JSONDecodeError as exc:
        raise InitDataError("user is not json") from exc
    if not isinstance(data, dict):
        raise InitDataError("user is not an object")
    user_id = data.get("id", data.get("user_id"))
    if not isinstance(user_id, int) or isinstance(user_id, bool):
        raise InitDataError("user id is missing")
    first_name = data.get("first_name")
    return WebAppUser(
        id=user_id,
        first_name=first_name if isinstance(first_name, str) else "",
        last_name=_optional_str(data, "last_name"),
        username=_optional_str(data, "username"),
        language_code=_optional_str(data, "language_code"),
        photo_url=_optional_str(data, "photo_url"),
    )


def _parse_chat_id(raw: str | None) -> int | None:
    if raw is None:
        return None
    try:
        data = orjson.loads(raw)
    except orjson.JSONDecodeError:
        return None
    chat_id = data.get("id") if isinstance(data, dict) else None
    return chat_id if isinstance(chat_id, int) else None


def parse_init_data(
    raw: str, bot_token: str, *, ttl_seconds: int, now: datetime | None = None
) -> InitData:
    if not raw or len(raw) > 8192:
        raise InitDataError("empty or oversized init data")
    pairs, received = _split(raw)
    expected = sign_init_data(pairs, bot_token)
    if not hmac.compare_digest(expected.encode(), received.lower().encode()):
        raise InitDataError("signature mismatch")
    try:
        auth_ts = int(pairs["auth_date"])
        auth_date = datetime.fromtimestamp(auth_ts, UTC)
    except (KeyError, ValueError, OverflowError, OSError) as exc:
        raise InitDataError("auth_date is invalid") from exc
    current = now or datetime.now(UTC)
    if auth_date > current + CLOCK_SKEW:
        raise InitDataError("auth_date is in the future")
    if current - auth_date > timedelta(seconds=ttl_seconds):
        raise InitDataError("init data expired")
    return InitData(
        user=_parse_user(pairs.get("user")),
        auth_date=auth_date,
        query_id=pairs.get("query_id"),
        start_param=pairs.get("start_param"),
        chat_id=_parse_chat_id(pairs.get("chat")),
    )


def _unauthorized(detail: str) -> HTTPException:
    return HTTPException(
        status.HTTP_401_UNAUTHORIZED, detail=detail, headers={"WWW-Authenticate": AUTH_SCHEME}
    )


def read_init_data(
    settings: Annotated[Settings, Depends(get_settings_dep)],
    authorization: Annotated[str | None, Header()] = None,
) -> InitData:
    if authorization is None:
        raise _unauthorized("missing_init_data")
    scheme, _, raw = authorization.partition(" ")
    if scheme.lower() != AUTH_SCHEME or not raw.strip():
        raise _unauthorized("missing_init_data")
    try:
        return parse_init_data(
            raw.strip(),
            settings.max_bot_token.get_secret_value(),
            ttl_seconds=settings.webapp_init_data_ttl_seconds,
        )
    except InitDataError as exc:
        log.info("webapp_init_data_rejected", reason=str(exc))
        raise _unauthorized("invalid_init_data") from exc


async def current_user(
    request: Request,
    init_data: Annotated[InitData, Depends(read_init_data)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> User:
    actor = max_types.User(
        user_id=init_data.user.id,
        first_name=init_data.user.first_name,
        last_name=init_data.user.last_name,
        username=init_data.user.username,
    )
    user = await upsert_user(session, actor)
    await session.commit()
    request.state.init_data = init_data
    return user


def require_teacher(user: Annotated[User, Depends(current_user)]) -> User:
    if user.role is not Role.TEACHER:
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="teacher_only")
    return user


CurrentUser = Annotated[User, Depends(current_user)]
Teacher = Annotated[User, Depends(require_teacher)]


def _media_key(bot_token: str) -> bytes:
    return hmac.new(b"yasno-webapp-media", bot_token.encode(), hashlib.sha256).digest()


def _media_signature(key: bytes, scope: str, expires: int) -> str:
    return hmac.new(key, f"{scope}:{expires}".encode(), hashlib.sha256).hexdigest()[:32]


def sign_media_token(scope: str, bot_token: str, *, now: datetime | None = None) -> str:
    current = int((now or datetime.now(UTC)).timestamp())
    expires = (current // MEDIA_TOKEN_BUCKET_SECONDS + MEDIA_TOKEN_BUCKETS) * (
        MEDIA_TOKEN_BUCKET_SECONDS
    )
    return f"{expires}.{_media_signature(_media_key(bot_token), scope, expires)}"


def verify_media_token(
    token: str, scope: str, bot_token: str, *, now: datetime | None = None
) -> bool:
    expires_raw, _, signature = token.partition(".")
    if not expires_raw.isdigit() or not signature:
        return False
    expires = int(expires_raw)
    if expires < int((now or datetime.now(UTC)).timestamp()):
        return False
    expected = _media_signature(_media_key(bot_token), scope, expires)
    return hmac.compare_digest(expected.encode(), signature.encode())
