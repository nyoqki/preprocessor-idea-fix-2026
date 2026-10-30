import asyncio

import pytest

from yasno.ai.fakes import FakeChat, FakeVision
from yasno.ai.http import ProviderHttpError
from yasno.ai.resilience import (
    AiUnavailableError,
    CircuitBreaker,
    FallbackChat,
    FallbackVision,
    ResilientChat,
    RetryPolicy,
)
from yasno.ai.types import ChatMessage, ProviderError, Role

FAST = RetryPolicy(attempts=3, timeout=1.0, base_delay=0)
MESSAGES = [ChatMessage(role=Role.USER, content="привет")]


class Clock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


class SlowChat:
    name = "slow"

    async def complete(self, *args: object, **kwargs: object) -> str:
        await asyncio.sleep(5)
        return "late"


async def test_retries_retryable_errors() -> None:
    inner = FakeChat([ProviderHttpError("p", "429", status=429, retryable=True), "ok"])
    assert await ResilientChat(inner, FAST).complete(MESSAGES) == "ok"
    assert len(inner.calls) == 2


async def test_does_not_retry_permanent_errors() -> None:
    inner = FakeChat([ProviderHttpError("p", "400", status=400), "ok"])
    with pytest.raises(ProviderError):
        await ResilientChat(inner, FAST).complete(MESSAGES)
    assert len(inner.calls) == 1


async def test_gives_up_after_attempts() -> None:
    error = ProviderError("p", "boom", retryable=True)
    inner = FakeChat([error, error, error, "ok"])
    with pytest.raises(ProviderError):
        await ResilientChat(inner, FAST).complete(MESSAGES)
    assert len(inner.calls) == 3


async def test_timeout_is_retryable_provider_error() -> None:
    policy = RetryPolicy(attempts=1, timeout=0.01, base_delay=0)
    with pytest.raises(ProviderError) as info:
        await ResilientChat(SlowChat(), policy).complete(MESSAGES)
    assert info.value.retryable


async def test_retry_after_is_respected() -> None:
    delays: list[float] = []

    async def sleep(delay: float) -> None:
        delays.append(delay)

    inner = FakeChat(
        [ProviderHttpError("p", "429", status=429, retryable=True, retry_after=2), "ok"]
    )
    await ResilientChat(inner, RetryPolicy(base_delay=0.5), sleep=sleep).complete(MESSAGES)
    assert delays == [2]


async def test_fallback_uses_next_provider() -> None:
    first = FakeChat([ProviderError("a", "down")], name="a")
    second = FakeChat(["from b"], name="b")
    chain = FallbackChat([first, second])
    assert await chain.complete(MESSAGES) == "from b"


async def test_fallback_raises_when_all_fail() -> None:
    chain = FallbackVision(
        [FakeVision(ProviderError("a", "down")), FakeVision(ProviderError("b", "down"))]
    )
    with pytest.raises(AiUnavailableError) as info:
        await chain.transcribe(b"img", "image/jpeg")
    assert len(info.value.errors) == 2


async def test_circuit_breaker_skips_failing_provider() -> None:
    clock = Clock()
    first = FakeChat(default=ProviderError("a", "down"), name="a")
    second = FakeChat(default="b", name="b")
    chain = FallbackChat([first, second], failures=2, cooldown=30, clock=clock)
    for _ in range(2):
        assert await chain.complete(MESSAGES) == "b"
    assert len(first.calls) == 2
    assert await chain.complete(MESSAGES) == "b"
    assert len(first.calls) == 2
    clock.now = 31
    first.default = "a is back"
    assert await chain.complete(MESSAGES) == "a is back"


def test_breaker_resets_on_success() -> None:
    clock = Clock()
    breaker = CircuitBreaker(failures=2, cooldown=10, clock=clock)
    breaker.record_failure()
    breaker.record_success()
    breaker.record_failure()
    assert not breaker.is_open
    breaker.record_failure()
    assert breaker.is_open
    clock.now = 10
    assert not breaker.is_open


async def test_open_breakers_still_try_providers_when_all_open() -> None:
    clock = Clock()
    only = FakeChat([ProviderError("a", "down"), "recovered"], name="a")
    chain = FallbackChat([only], failures=1, cooldown=60, clock=clock)
    with pytest.raises(AiUnavailableError):
        await chain.complete(MESSAGES)
    assert await chain.complete(MESSAGES) == "recovered"
