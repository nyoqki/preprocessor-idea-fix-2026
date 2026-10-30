import json
from collections.abc import AsyncIterator

import httpx
import orjson
import pytest
import respx

from yasno.ai.gigachat import GigaChatChat, GigaChatClient, GigaChatVision
from yasno.ai.http import ProviderHttpError
from yasno.ai.types import ChatMessage, Role

BASE = "https://giga.test/api/v1"
AUTH = "https://auth.test/api/v2/oauth"
MESSAGES = [ChatMessage(role=Role.USER, content="привет")]


class Clock:
    def __init__(self) -> None:
        self.now = 1_790_000_000.0

    def __call__(self) -> float:
        return self.now


def completion(content: str) -> dict[str, object]:
    return {
        "choices": [{"index": 0, "message": {"role": "assistant", "content": content}}],
        "created": 1,
        "model": "GigaChat-2-Max",
        "object": "chat.completion",
        "usage": {"prompt_tokens": 3, "completion_tokens": 2, "total_tokens": 5},
    }


@pytest.fixture
def clock() -> Clock:
    return Clock()


@pytest.fixture
async def client(clock: Clock) -> AsyncIterator[GigaChatClient]:
    gc = GigaChatClient("Y3JlZHM=", base_url=BASE, auth_url=AUTH, verify=False, clock=clock)
    yield gc
    await gc.aclose()


def token(value: str, expires_at_ms: float) -> httpx.Response:
    return httpx.Response(200, json={"access_token": value, "expires_at": int(expires_at_ms)})


@respx.mock
async def test_oauth_request_and_cached_token(client: GigaChatClient, clock: Clock) -> None:
    auth = respx.post(AUTH).mock(return_value=token("t1", (clock.now + 1800) * 1000))
    chat = respx.post(f"{BASE}/chat/completions").respond(json=completion("ok"))
    model = GigaChatChat(client, "GigaChat-2-Max")
    assert await model.complete(MESSAGES) == "ok"
    assert await model.complete(MESSAGES) == "ok"
    assert auth.call_count == 1
    request = auth.calls.last.request
    assert request.headers["Authorization"] == "Basic Y3JlZHM="
    assert request.headers["RqUID"]
    assert request.content == b"scope=GIGACHAT_API_PERS"
    assert chat.calls.last.request.headers["Authorization"] == "Bearer t1"
    body = orjson.loads(chat.calls.last.request.content)
    assert body["model"] == "GigaChat-2-Max"
    assert body["messages"] == [{"role": "user", "content": "привет"}]


@respx.mock
async def test_token_is_refreshed_before_expiry(client: GigaChatClient, clock: Clock) -> None:
    auth = respx.post(AUTH)
    auth.side_effect = [
        token("t1", (clock.now + 600) * 1000),
        token("t2", (clock.now + 3000) * 1000),
    ]
    chat = respx.post(f"{BASE}/chat/completions").respond(json=completion("ok"))
    model = GigaChatChat(client, "GigaChat-2-Max")
    await model.complete(MESSAGES)
    clock.now += 560
    await model.complete(MESSAGES)
    assert auth.call_count == 2
    assert chat.calls.last.request.headers["Authorization"] == "Bearer t2"


@respx.mock
async def test_token_in_seconds_and_tok_format(client: GigaChatClient, clock: Clock) -> None:
    respx.post(AUTH).respond(json={"tok": "short", "exp": int(clock.now + 1800)})
    assert await client.token() == "short"
    assert await client.token() == "short"


@respx.mock
async def test_unauthorized_triggers_single_reauth(client: GigaChatClient, clock: Clock) -> None:
    auth = respx.post(AUTH)
    auth.side_effect = [
        token("stale", (clock.now + 1800) * 1000),
        token("fresh", (clock.now + 1800) * 1000),
    ]
    chat = respx.post(f"{BASE}/chat/completions")
    chat.side_effect = [httpx.Response(401), httpx.Response(200, json=completion("ok"))]
    assert await GigaChatChat(client, "GigaChat-2").complete(MESSAGES) == "ok"
    assert chat.calls.last.request.headers["Authorization"] == "Bearer fresh"


@respx.mock
async def test_rate_limit_is_retryable(client: GigaChatClient, clock: Clock) -> None:
    respx.post(AUTH).mock(return_value=token("t", (clock.now + 1800) * 1000))
    respx.post(f"{BASE}/chat/completions").respond(429, headers={"Retry-After": "3"})
    with pytest.raises(ProviderHttpError) as info:
        await GigaChatChat(client, "GigaChat-2").complete(MESSAGES)
    assert info.value.retryable
    assert info.value.retry_after == 3


@respx.mock
async def test_bad_credentials_are_not_retryable(client: GigaChatClient) -> None:
    respx.post(AUTH).respond(401, json={"code": 6, "message": "credentials doesn't match"})
    with pytest.raises(ProviderHttpError) as info:
        await client.token()
    assert not info.value.retryable


@respx.mock
async def test_vision_uploads_attaches_and_deletes_image(
    client: GigaChatClient, clock: Clock
) -> None:
    respx.post(AUTH).mock(return_value=token("t", (clock.now + 1800) * 1000))
    upload = respx.post(f"{BASE}/files").respond(json={"id": "file-1", "object": "file"})
    payload = {"lines": [{"latex": "x = 1", "confidence": 0.8}]}
    chat = respx.post(f"{BASE}/chat/completions").respond(json=completion(json.dumps(payload)))
    delete = respx.post(f"{BASE}/files/file-1/delete").respond(json={"id": "file-1"})
    result = await GigaChatVision(client, "GigaChat-2-Max").transcribe(b"img", "image/png")
    assert result.lines[0].latex == "x = 1"
    form = upload.calls.last.request.content
    assert b'name="purpose"' in form
    assert b"general" in form
    assert b'filename="image.png"' in form
    message = orjson.loads(chat.calls.last.request.content)["messages"][0]
    assert message["attachments"] == ["file-1"]
    assert delete.call_count == 1


@respx.mock
async def test_vision_deletes_image_even_when_chat_fails(
    client: GigaChatClient, clock: Clock
) -> None:
    respx.post(AUTH).mock(return_value=token("t", (clock.now + 1800) * 1000))
    respx.post(f"{BASE}/files").respond(json={"id": "file-2"})
    respx.post(f"{BASE}/chat/completions").respond(500)
    delete = respx.post(f"{BASE}/files/file-2/delete").respond(500)
    with pytest.raises(ProviderHttpError):
        await GigaChatVision(client, "GigaChat-2-Max").transcribe(b"img", "image/jpeg")
    assert delete.call_count == 1
