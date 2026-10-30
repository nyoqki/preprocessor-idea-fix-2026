import asyncio
import random
import time
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass

import structlog

from yasno.ai.http import ProviderHttpError
from yasno.ai.types import (
    ChatMessage,
    ChatModel,
    Embedder,
    EmbeddingKind,
    JsonSchema,
    OcrEngine,
    OcrResult,
    ProviderError,
    Transcription,
    VisionModel,
)

log = structlog.get_logger(__name__)

type Sleep = Callable[[float], Awaitable[None]]
type Clock = Callable[[], float]


class AiUnavailableError(ProviderError):
    def __init__(self, operation: str, errors: Sequence[ProviderError]) -> None:
        details = "; ".join(str(error) for error in errors) or "no providers"
        super().__init__("fallback", f"{operation} failed: {details}", retryable=False)
        self.errors = list(errors)


@dataclass(frozen=True, slots=True)
class RetryPolicy:
    attempts: int = 3
    timeout: float = 60.0
    base_delay: float = 0.5
    max_delay: float = 8.0

    def delay(self, attempt: int, error: ProviderError) -> float:
        if isinstance(error, ProviderHttpError) and error.retry_after is not None:
            return min(error.retry_after, self.max_delay)
        if self.base_delay <= 0:
            return 0.0
        backoff = min(self.base_delay * float(2 ** (attempt - 1)), self.max_delay)
        return backoff + random.uniform(0, self.base_delay / 2)  # noqa: S311


async def call_with_retry[T](
    provider: str,
    operation: str,
    call: Callable[[], Awaitable[T]],
    policy: RetryPolicy,
    *,
    sleep: Sleep = asyncio.sleep,
) -> T:
    attempt = 0
    while True:
        attempt += 1
        try:
            async with asyncio.timeout(policy.timeout):
                return await call()
        except TimeoutError:
            error: ProviderError = ProviderError(provider, "call timed out", retryable=True)
        except ProviderError as exc:
            error = exc
        except Exception as exc:
            log.exception("ai_provider_crashed", provider=provider, operation=operation)
            raise ProviderError(provider, f"unexpected {type(exc).__name__}") from exc
        if not error.retryable or attempt >= policy.attempts:
            log.warning(
                "ai_call_failed",
                provider=provider,
                operation=operation,
                attempt=attempt,
                retryable=error.retryable,
                error=str(error),
            )
            raise error
        delay = policy.delay(attempt, error)
        log.warning(
            "ai_call_retry",
            provider=provider,
            operation=operation,
            attempt=attempt,
            retry_in=round(delay, 2),
            error=str(error),
        )
        await sleep(delay)


class ResilientChat:
    def __init__(
        self, inner: ChatModel, policy: RetryPolicy, *, sleep: Sleep = asyncio.sleep
    ) -> None:
        self.inner = inner
        self.name = inner.name
        self._policy = policy
        self._sleep = sleep

    async def complete(
        self,
        messages: Sequence[ChatMessage],
        *,
        json_schema: JsonSchema | None = None,
        temperature: float = 0.2,
        max_tokens: int = 800,
    ) -> str:
        return await call_with_retry(
            self.name,
            "chat",
            lambda: self.inner.complete(
                messages, json_schema=json_schema, temperature=temperature, max_tokens=max_tokens
            ),
            self._policy,
            sleep=self._sleep,
        )


class ResilientVision:
    def __init__(
        self, inner: VisionModel, policy: RetryPolicy, *, sleep: Sleep = asyncio.sleep
    ) -> None:
        self.inner = inner
        self.name = inner.name
        self._policy = policy
        self._sleep = sleep

    async def transcribe(self, image: bytes, mime_type: str) -> Transcription:
        return await call_with_retry(
            self.name,
            "vision",
            lambda: self.inner.transcribe(image, mime_type),
            self._policy,
            sleep=self._sleep,
        )


class ResilientOcr:
    def __init__(
        self, inner: OcrEngine, policy: RetryPolicy, *, sleep: Sleep = asyncio.sleep
    ) -> None:
        self.inner = inner
        self.name = inner.name
        self._policy = policy
        self._sleep = sleep

    async def recognize(self, image: bytes, mime_type: str) -> OcrResult:
        return await call_with_retry(
            self.name,
            "ocr",
            lambda: self.inner.recognize(image, mime_type),
            self._policy,
            sleep=self._sleep,
        )


class ResilientEmbedder:
    def __init__(
        self, inner: Embedder, policy: RetryPolicy, *, sleep: Sleep = asyncio.sleep
    ) -> None:
        self.inner = inner
        self.name = inner.name
        self.dimensions = inner.dimensions
        self._policy = policy
        self._sleep = sleep

    async def embed(self, texts: Sequence[str], *, kind: EmbeddingKind) -> list[list[float]]:
        return await call_with_retry(
            self.name,
            "embed",
            lambda: self.inner.embed(texts, kind=kind),
            self._policy,
            sleep=self._sleep,
        )


class CircuitBreaker:
    def __init__(
        self, *, failures: int = 3, cooldown: float = 60.0, clock: Clock = time.monotonic
    ) -> None:
        self._threshold = failures
        self._cooldown = cooldown
        self._clock = clock
        self._failures = 0
        self._open_until = 0.0

    @property
    def is_open(self) -> bool:
        return self._clock() < self._open_until

    def record_success(self) -> None:
        self._failures = 0
        self._open_until = 0.0

    def record_failure(self) -> None:
        self._failures += 1
        if self._failures >= self._threshold:
            self._open_until = self._clock() + self._cooldown
            self._failures = 0


class _Fallback[P: (ChatModel, VisionModel)]:
    def __init__(
        self,
        providers: Sequence[P],
        *,
        failures: int = 3,
        cooldown: float = 60.0,
        clock: Clock = time.monotonic,
    ) -> None:
        if not providers:
            raise ValueError("at least one provider is required")
        self.providers: list[P] = list(providers)
        self.name = " > ".join(provider.name for provider in self.providers)
        self._breakers = [
            CircuitBreaker(failures=failures, cooldown=cooldown, clock=clock)
            for _ in self.providers
        ]

    def _candidates(self) -> list[tuple[P, CircuitBreaker]]:
        pairs = list(zip(self.providers, self._breakers, strict=True))
        closed = [pair for pair in pairs if not pair[1].is_open]
        for provider, breaker in pairs:
            if breaker.is_open:
                log.info("ai_provider_skipped", provider=provider.name, reason="circuit_open")
        return closed or pairs

    async def _run[T](self, operation: str, call: Callable[[P], Awaitable[T]]) -> T:
        errors: list[ProviderError] = []
        for provider, breaker in self._candidates():
            try:
                result = await call(provider)
            except ProviderError as exc:
                breaker.record_failure()
                errors.append(exc)
                log.warning(
                    "ai_fallback",
                    provider=provider.name,
                    operation=operation,
                    error=str(exc),
                )
                continue
            breaker.record_success()
            return result
        raise AiUnavailableError(operation, errors)


class FallbackChat(_Fallback[ChatModel]):
    async def complete(
        self,
        messages: Sequence[ChatMessage],
        *,
        json_schema: JsonSchema | None = None,
        temperature: float = 0.2,
        max_tokens: int = 800,
    ) -> str:
        return await self._run(
            "chat",
            lambda provider: provider.complete(
                messages, json_schema=json_schema, temperature=temperature, max_tokens=max_tokens
            ),
        )


class FallbackVision(_Fallback[VisionModel]):
    async def transcribe(self, image: bytes, mime_type: str) -> Transcription:
        return await self._run("vision", lambda provider: provider.transcribe(image, mime_type))
