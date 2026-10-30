import asyncio
import contextlib
import ssl
import time
import uuid
from collections.abc import Callable, Mapping, Sequence
from typing import Any

import httpx
import structlog

from yasno.ai import prompts
from yasno.ai.http import ProviderHttp, ProviderHttpError, Usage, first_choice_text, log_call
from yasno.ai.transcription import transcription_with_repair
from yasno.ai.types import ChatMessage, JsonSchema, Transcription

log = structlog.get_logger(__name__)

PROVIDER = "gigachat"
BASE_URL = "https://api.giga.chat/v1"
AUTH_URL = "https://ngw.devices.sberbank.ru:9443/api/v2/oauth"
SECONDS_THRESHOLD = 10_000_000_000

_EXTENSIONS = {"image/jpeg": "jpg", "image/png": "png", "image/webp": "webp", "image/gif": "gif"}


class GigaChatClient:
    def __init__(
        self,
        credentials: str,
        *,
        scope: str = "GIGACHAT_API_PERS",
        base_url: str = BASE_URL,
        auth_url: str = AUTH_URL,
        timeout: float = 60.0,
        refresh_margin: float = 60.0,
        transport: httpx.AsyncBaseTransport | None = None,
        verify: ssl.SSLContext | bool | None = None,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self._credentials = credentials
        self._scope = scope
        self._auth_url = auth_url
        self._refresh_margin = refresh_margin
        self._clock = clock
        self._token: str | None = None
        self._expires_at = 0.0
        self._lock = asyncio.Lock()
        self.http = ProviderHttp(
            PROVIDER,
            base_url=base_url,
            headers={"Accept": "application/json"},
            timeout=timeout,
            transport=transport,
            verify=verify,
        )

    async def aclose(self) -> None:
        await self.http.aclose()

    def _token_valid(self) -> bool:
        return self._token is not None and self._clock() < self._expires_at - self._refresh_margin

    def invalidate(self) -> None:
        self._token = None
        self._expires_at = 0.0

    async def token(self) -> str:
        if self._token_valid() and self._token is not None:
            return self._token
        async with self._lock:
            if self._token_valid() and self._token is not None:
                return self._token
            data = await self.http.send_json(
                "POST",
                self._auth_url,
                data={"scope": self._scope},
                headers={
                    "Authorization": f"Basic {self._credentials}",
                    "RqUID": str(uuid.uuid4()),
                    "Content-Type": "application/x-www-form-urlencoded",
                },
            )
            token, expires_at = self._parse_token(data)
            self._token = token
            self._expires_at = expires_at
            log.info("gigachat_token_refreshed", expires_in=round(expires_at - self._clock()))
            return token

    def _parse_token(self, data: Any) -> tuple[str, float]:
        if not isinstance(data, Mapping):
            raise ProviderHttpError(PROVIDER, "unexpected token payload")
        token = data.get("access_token", data.get("tok"))
        expires = data.get("expires_at", data.get("exp"))
        if not isinstance(token, str) or not isinstance(expires, int | float):
            raise ProviderHttpError(PROVIDER, "unexpected token payload")
        if expires == 0:
            return token, float("inf")
        seconds = float(expires) if expires < SECONDS_THRESHOLD else float(expires) / 1000
        return token, seconds

    async def _authorized(self, method: str, path: str, **kwargs: Any) -> httpx.Response:
        token = await self.token()
        headers = {"Authorization": f"Bearer {token}"}
        return await self.http.send(method, path, headers=headers, **kwargs)

    async def request(self, method: str, path: str, **kwargs: Any) -> httpx.Response:
        try:
            return await self._authorized(method, path, **kwargs)
        except ProviderHttpError as exc:
            if exc.status != 401:
                raise
        self.invalidate()
        return await self._authorized(method, path, **kwargs)

    async def chat(
        self,
        model: str,
        messages: Sequence[Mapping[str, Any]],
        *,
        temperature: float = 0.2,
        max_tokens: int = 800,
        operation: str = "chat",
    ) -> str:
        body = {
            "model": model,
            "messages": list(messages),
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        started = time.monotonic()
        response = await self.request("POST", "chat/completions", json=body)
        try:
            data = response.json()
        except ValueError as exc:
            raise ProviderHttpError(PROVIDER, "response is not valid JSON", retryable=True) from exc
        text = first_choice_text(PROVIDER, data)
        log_call(PROVIDER, model, operation, started, Usage.from_payload(data))
        return text

    async def upload(self, content: bytes, mime_type: str) -> str:
        extension = _EXTENSIONS.get(mime_type, "jpg")
        response = await self.request(
            "POST",
            "files",
            files={"file": (f"image.{extension}", content, mime_type)},
            data={"purpose": "general"},
        )
        try:
            file_id = response.json()["id"]
        except (ValueError, KeyError, TypeError) as exc:
            raise ProviderHttpError(PROVIDER, "unexpected upload payload") from exc
        return str(file_id)

    async def delete_file(self, file_id: str) -> None:
        await self.request("POST", f"files/{file_id}/delete")


class GigaChatChat:
    def __init__(self, client: GigaChatClient, model: str) -> None:
        self.client = client
        self.model = model
        self.name = f"{PROVIDER}:{model}"

    async def complete(
        self,
        messages: Sequence[ChatMessage],
        *,
        json_schema: JsonSchema | None = None,
        temperature: float = 0.2,
        max_tokens: int = 800,
    ) -> str:
        payload = [{"role": m.role.value, "content": m.content} for m in messages]
        return await self.client.chat(
            self.model, payload, temperature=temperature, max_tokens=max_tokens
        )


class GigaChatVision:
    def __init__(self, client: GigaChatClient, model: str, *, max_tokens: int = 2000) -> None:
        self.client = client
        self.model = model
        self.name = f"{PROVIDER}:{model}"
        self._max_tokens = max_tokens

    async def transcribe(self, image: bytes, mime_type: str) -> Transcription:
        file_id = await self.client.upload(image, mime_type)
        try:
            raw = await self.client.chat(
                self.model,
                [{"role": "user", "content": prompts.TRANSCRIBE, "attachments": [file_id]}],
                temperature=0.01,
                max_tokens=self._max_tokens,
                operation="vision",
            )
        finally:
            await self._forget(file_id)

        async def repair(instruction: str) -> str:
            return await self.client.chat(
                self.model,
                [
                    {"role": "user", "content": prompts.TRANSCRIBE},
                    {"role": "assistant", "content": raw},
                    {"role": "user", "content": instruction},
                ],
                temperature=0.01,
                max_tokens=self._max_tokens,
                operation="vision_repair",
            )

        return await transcription_with_repair(self.name, raw, repair)

    async def _forget(self, file_id: str) -> None:
        with contextlib.suppress(ProviderHttpError):
            await self.client.delete_file(file_id)
