import ssl
import time
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

import httpx
import orjson
import structlog

from yasno.ai.types import ProviderError
from yasno.max.tls import build_ssl_context

log = structlog.get_logger(__name__)

RETRYABLE_STATUSES = frozenset({408, 425, 429, 500, 502, 503, 504})


class ProviderHttpError(ProviderError):
    def __init__(
        self,
        provider: str,
        message: str,
        *,
        status: int | None = None,
        retryable: bool = False,
        retry_after: float | None = None,
    ) -> None:
        super().__init__(provider, message, retryable=retryable)
        self.status = status
        self.retry_after = retry_after


@dataclass(frozen=True, slots=True)
class Usage:
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    total_tokens: int | None = None

    @classmethod
    def from_payload(cls, data: Any) -> "Usage":
        if not isinstance(data, Mapping):
            return cls()
        usage = data.get("usage")
        if not isinstance(usage, Mapping):
            return cls()

        def number(key: str) -> int | None:
            value = usage.get(key)
            try:
                return int(value) if value is not None else None
            except (TypeError, ValueError):
                return None

        return cls(number("prompt_tokens"), number("completion_tokens"), number("total_tokens"))


def log_call(
    provider: str,
    model: str,
    operation: str,
    started: float,
    usage: Usage | None = None,
    **extra: Any,
) -> None:
    usage = usage or Usage()
    log.info(
        "ai_call",
        provider=provider,
        model=model,
        operation=operation,
        latency_ms=round((time.monotonic() - started) * 1000),
        prompt_tokens=usage.prompt_tokens,
        completion_tokens=usage.completion_tokens,
        total_tokens=usage.total_tokens,
        **extra,
    )


def _retry_after(response: httpx.Response) -> float | None:
    value = response.headers.get("Retry-After")
    if value is None:
        return None
    try:
        return max(float(value), 0.0)
    except ValueError:
        return None


class ProviderHttp:
    def __init__(
        self,
        provider: str,
        *,
        base_url: str,
        headers: Mapping[str, str] | None = None,
        timeout: float = 60.0,
        transport: httpx.AsyncBaseTransport | None = None,
        verify: ssl.SSLContext | bool | None = None,
    ) -> None:
        self.provider = provider
        self._client = httpx.AsyncClient(
            base_url=base_url.rstrip("/") + "/",
            headers=dict(headers or {}),
            timeout=httpx.Timeout(timeout, connect=10.0),
            transport=transport,
            verify=verify if verify is not None else build_ssl_context(),
        )

    async def aclose(self) -> None:
        await self._client.aclose()

    async def send(
        self,
        method: str,
        path: str,
        *,
        json: Any = None,
        data: Mapping[str, str] | None = None,
        files: Mapping[str, Any] | None = None,
        headers: Mapping[str, str] | None = None,
    ) -> httpx.Response:
        request_headers = dict(headers or {})
        content: bytes | None = None
        if json is not None:
            content = orjson.dumps(json)
            request_headers["Content-Type"] = "application/json"
        try:
            response = await self._client.request(
                method,
                path.lstrip("/") if "://" not in path else path,
                content=content,
                data=data,
                files=files,
                headers=request_headers,
            )
        except httpx.TimeoutException as exc:
            raise ProviderHttpError(self.provider, "request timed out", retryable=True) from exc
        except httpx.TransportError as exc:
            raise ProviderHttpError(
                self.provider, f"transport error: {type(exc).__name__}", retryable=True
            ) from exc
        if response.is_success:
            return response
        raise ProviderHttpError(
            self.provider,
            f"HTTP {response.status_code}: {response.text[:200]}",
            status=response.status_code,
            retryable=response.status_code in RETRYABLE_STATUSES,
            retry_after=_retry_after(response),
        )

    async def send_json(self, method: str, path: str, **kwargs: Any) -> Any:
        response = await self.send(method, path, **kwargs)
        return decode_json(self.provider, response.content)


def decode_json(provider: str, content: bytes) -> Any:
    try:
        return orjson.loads(content)
    except orjson.JSONDecodeError as exc:
        raise ProviderHttpError(provider, "response is not valid JSON", retryable=True) from exc


def first_choice_text(provider: str, data: Any) -> str:
    try:
        content = data["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as exc:
        raise ProviderHttpError(provider, "unexpected completion payload") from exc
    if isinstance(content, list):
        content = "".join(
            str(part.get("text", "")) for part in content if isinstance(part, Mapping)
        )
    if not isinstance(content, str) or not content.strip():
        if data["choices"][0].get("finish_reason") == "length":
            raise ProviderHttpError(provider, "completion cut off by max_tokens before any answer")
        raise ProviderHttpError(provider, "empty completion", retryable=True)
    return content
