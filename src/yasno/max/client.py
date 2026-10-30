import asyncio
import random
import time
from collections.abc import Iterable, Mapping
from types import TracebackType
from typing import Any, Self

import httpx
import orjson
import structlog
from pydantic import BaseModel

from yasno.max.keyboard import AttachmentRequest
from yasno.max.tls import build_ssl_context
from yasno.max.types import (
    BotInfo,
    Chat,
    ChatMember,
    ChatMembers,
    Message,
    SendMessageResult,
    Subscriptions,
    TextFormat,
    UpdateList,
    UploadEndpoint,
)

log = structlog.get_logger(__name__)

RETRYABLE_STATUSES = frozenset({429, 500, 502, 503, 504})


class MaxApiError(Exception):
    def __init__(self, status: int, code: str | None, message: str) -> None:
        super().__init__(f"{status} {code or ''} {message}".strip())
        self.status = status
        self.code = code
        self.message = message


class RateLimiter:
    def __init__(self, rate: float) -> None:
        self._interval = 1.0 / rate
        self._lock = asyncio.Lock()
        self._next = 0.0

    async def acquire(self) -> None:
        async with self._lock:
            now = time.monotonic()
            wait = self._next - now
            self._next = max(now, self._next) + self._interval
        if wait > 0:
            await asyncio.sleep(wait)


class MaxClient:
    def __init__(
        self,
        token: str,
        *,
        base_url: str = "https://platform-api2.max.ru",
        transport: httpx.AsyncBaseTransport | None = None,
        verify: Any = None,
        timeout: float = 30.0,
        max_retries: int = 4,
        rate_per_second: float = 25.0,
    ) -> None:
        ssl_context = verify if verify is not None else build_ssl_context()
        self._http = httpx.AsyncClient(
            base_url=base_url,
            headers={"Authorization": token},
            timeout=httpx.Timeout(timeout, connect=10.0),
            transport=transport,
            verify=ssl_context,
        )
        self._files = httpx.AsyncClient(
            timeout=httpx.Timeout(60.0, connect=10.0),
            transport=transport,
            verify=ssl_context,
            follow_redirects=True,
        )
        self._max_retries = max_retries
        self._limiter = RateLimiter(rate_per_second)

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        await self._http.aclose()
        await self._files.aclose()

    async def _request(
        self,
        method: str,
        path: str,
        *,
        params: Mapping[str, Any] | None = None,
        json: Any = None,
        request_timeout: float | None = None,
    ) -> Any:
        query = {k: v for k, v in (params or {}).items() if v is not None}
        content = orjson.dumps(json) if json is not None else None
        headers = {"Content-Type": "application/json"} if content is not None else None
        attempt = 0
        while True:
            await self._limiter.acquire()
            try:
                response = await self._http.request(
                    method,
                    path,
                    params=query,
                    content=content,
                    headers=headers,
                    timeout=request_timeout
                    if request_timeout is not None
                    else httpx.USE_CLIENT_DEFAULT,
                )
            except httpx.TransportError as exc:
                if attempt >= self._max_retries:
                    raise
                attempt += 1
                delay = self._backoff(attempt)
                log.warning("max_transport_error", path=path, error=str(exc), retry_in=delay)
                await asyncio.sleep(delay)
                continue

            if response.status_code in RETRYABLE_STATUSES and attempt < self._max_retries:
                attempt += 1
                delay = self._retry_after(response) or self._backoff(attempt)
                log.warning(
                    "max_retryable_status",
                    path=path,
                    status=response.status_code,
                    retry_in=delay,
                )
                await asyncio.sleep(delay)
                continue

            if response.is_success:
                return orjson.loads(response.content) if response.content else None
            raise self._error(response)

    @staticmethod
    def _backoff(attempt: int) -> float:
        return float(min(2 ** (attempt - 1), 16) + random.uniform(0, 0.5))  # noqa: S311

    @staticmethod
    def _retry_after(response: httpx.Response) -> float | None:
        value = response.headers.get("Retry-After")
        if value is None:
            return None
        try:
            return max(float(value), 0.0)
        except ValueError:
            return None

    @staticmethod
    def _error(response: httpx.Response) -> MaxApiError:
        code: str | None = None
        message = response.text
        try:
            data = orjson.loads(response.content)
        except orjson.JSONDecodeError:
            data = None
        if isinstance(data, dict):
            code = data.get("code")
            message = data.get("message") or message
        return MaxApiError(response.status_code, code, message)

    @staticmethod
    def _parse[M: BaseModel](model: type[M], data: Any) -> M:
        return model.model_validate(data)

    async def get_me(self) -> BotInfo:
        return self._parse(BotInfo, await self._request("GET", "/me"))

    async def set_commands(self, commands: Iterable[tuple[str, str]]) -> None:
        body = {"commands": [{"name": n, "description": d} for n, d in commands]}
        await self._request("PATCH", "/me/commands", json=body)

    async def send_message(
        self,
        *,
        user_id: int | None = None,
        chat_id: int | None = None,
        text: str | None = None,
        attachments: list[AttachmentRequest] | None = None,
        text_format: TextFormat | None = TextFormat.MARKDOWN,
        notify: bool = True,
        disable_link_preview: bool = True,
    ) -> Message:
        if (user_id is None) == (chat_id is None):
            raise ValueError("exactly one of user_id or chat_id is required")
        body = self._message_body(text, attachments, text_format, notify=notify)
        data = await self._request(
            "POST",
            "/messages",
            params={
                "user_id": user_id,
                "chat_id": chat_id,
                "disable_link_preview": str(disable_link_preview).lower(),
            },
            json=body,
        )
        return self._parse(SendMessageResult, data).message

    async def edit_message(
        self,
        message_id: str,
        *,
        text: str | None = None,
        attachments: list[AttachmentRequest] | None = None,
        text_format: TextFormat | None = TextFormat.MARKDOWN,
    ) -> None:
        body = self._message_body(text, attachments, text_format, notify=False)
        await self._request("PUT", "/messages", params={"message_id": message_id}, json=body)

    async def delete_message(self, message_id: str) -> None:
        await self._request("DELETE", "/messages", params={"message_id": message_id})

    async def answer_callback(
        self,
        callback_id: str,
        *,
        notification: str | None = None,
        text: str | None = None,
        attachments: list[AttachmentRequest] | None = None,
        text_format: TextFormat | None = TextFormat.MARKDOWN,
    ) -> None:
        body: dict[str, Any] = {}
        if notification is not None:
            body["notification"] = notification
        if text is not None or attachments is not None:
            body["message"] = self._message_body(text, attachments, text_format, notify=False)
        await self._request("POST", "/answers", params={"callback_id": callback_id}, json=body)

    async def send_action(self, chat_id: int, action: str = "typing_on") -> None:
        await self._request("POST", f"/chats/{chat_id}/actions", json={"action": action})

    async def get_chat(self, chat_id: int) -> Chat:
        return self._parse(Chat, await self._request("GET", f"/chats/{chat_id}"))

    async def get_my_membership(self, chat_id: int) -> ChatMember:
        return self._parse(ChatMember, await self._request("GET", f"/chats/{chat_id}/members/me"))

    async def get_members(self, chat_id: int, *, marker: int | None = None) -> ChatMembers:
        data = await self._request(
            "GET", f"/chats/{chat_id}/members", params={"marker": marker, "count": 100}
        )
        return self._parse(ChatMembers, data)

    async def get_updates(
        self,
        *,
        marker: int | None = None,
        wait_seconds: int = 30,
        limit: int = 100,
        types: Iterable[str] | None = None,
    ) -> UpdateList:
        data = await self._request(
            "GET",
            "/updates",
            params={
                "marker": marker,
                "timeout": wait_seconds,
                "limit": limit,
                "types": ",".join(types) if types else None,
            },
            request_timeout=wait_seconds + 15,
        )
        return self._parse(UpdateList, data)

    async def get_subscriptions(self) -> Subscriptions:
        return self._parse(Subscriptions, await self._request("GET", "/subscriptions"))

    async def subscribe(
        self, url: str, *, secret: str | None = None, update_types: Iterable[str] | None = None
    ) -> None:
        body: dict[str, Any] = {"url": url}
        if secret:
            body["secret"] = secret
        if update_types is not None:
            body["update_types"] = list(update_types)
        await self._request("POST", "/subscriptions", json=body)

    async def unsubscribe(self, url: str) -> None:
        await self._request("DELETE", "/subscriptions", params={"url": url})

    async def upload_image(self, content: bytes, filename: str = "image.png") -> str:
        endpoint = self._parse(
            UploadEndpoint, await self._request("POST", "/uploads", params={"type": "image"})
        )
        await self._limiter.acquire()
        response = await self._files.post(endpoint.url, files={"data": (filename, content)})
        if not response.is_success:
            raise self._error(response)
        data = orjson.loads(response.content)
        photos = data.get("photos") if isinstance(data, dict) else None
        if isinstance(photos, dict) and photos:
            token = next(iter(photos.values())).get("token")
            if isinstance(token, str):
                return token
        if isinstance(data, dict) and isinstance(data.get("token"), str):
            return str(data["token"])
        raise MaxApiError(response.status_code, "upload.no_token", "upload returned no token")

    async def download(self, url: str, *, max_bytes: int = 20 * 1024 * 1024) -> bytes:
        async with self._files.stream("GET", url) as response:
            if not response.is_success:
                await response.aread()
                raise self._error(response)
            chunks: list[bytes] = []
            total = 0
            async for chunk in response.aiter_bytes():
                total += len(chunk)
                if total > max_bytes:
                    raise MaxApiError(413, "download.too_large", f"file exceeds {max_bytes} bytes")
                chunks.append(chunk)
            return b"".join(chunks)

    @staticmethod
    def _message_body(
        text: str | None,
        attachments: list[AttachmentRequest] | None,
        text_format: TextFormat | None,
        *,
        notify: bool,
    ) -> dict[str, Any]:
        body: dict[str, Any] = {"notify": notify}
        if text is not None:
            body["text"] = text
        if attachments is not None:
            body["attachments"] = attachments
        if text_format is not None and text is not None:
            body["format"] = text_format.value
        return body
