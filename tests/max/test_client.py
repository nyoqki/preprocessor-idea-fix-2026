import httpx
import orjson
import pytest
import respx

from yasno.max import keyboard
from yasno.max.client import MaxApiError, MaxClient

BASE = "https://api.test"


@pytest.fixture
async def client() -> MaxClient:
    return MaxClient("secret-token", base_url=BASE, verify=False, rate_per_second=1000)


@respx.mock
async def test_sends_token_in_authorization_header(client: MaxClient) -> None:
    route = respx.get(f"{BASE}/me").respond(
        json={"user_id": 1, "first_name": "bot", "is_bot": True, "username": "yasno_bot"}
    )
    me = await client.get_me()
    assert me.username == "yasno_bot"
    assert route.calls.last.request.headers["Authorization"] == "secret-token"


@respx.mock
async def test_send_message_builds_body(client: MaxClient) -> None:
    route = respx.post(f"{BASE}/messages").respond(
        json={
            "message": {
                "recipient": {"chat_type": "dialog", "user_id": 7},
                "timestamp": 1,
                "body": {"mid": "m1", "seq": 1, "text": "hi"},
            }
        }
    )
    kb = keyboard.inline_keyboard([[keyboard.callback("Да", "confirm:1")]])
    message = await client.send_message(user_id=7, text="hi", attachments=[kb])
    request = route.calls.last.request
    assert request.url.params["user_id"] == "7"
    body = orjson.loads(request.content)
    assert body["text"] == "hi"
    assert body["format"] == "markdown"
    assert body["attachments"][0]["payload"]["buttons"][0][0]["payload"] == "confirm:1"
    assert message.body.mid == "m1"


async def test_send_message_requires_single_recipient(client: MaxClient) -> None:
    with pytest.raises(ValueError, match="exactly one"):
        await client.send_message(text="x")


@respx.mock
async def test_retries_on_rate_limit(client: MaxClient) -> None:
    route = respx.get(f"{BASE}/me")
    route.side_effect = [
        httpx.Response(429, headers={"Retry-After": "0"}),
        httpx.Response(200, json={"user_id": 1, "first_name": "b", "is_bot": True}),
    ]
    me = await client.get_me()
    assert me.user_id == 1
    assert route.call_count == 2


@respx.mock
async def test_raises_api_error_with_code(client: MaxClient) -> None:
    respx.post(f"{BASE}/answers").respond(
        400, json={"code": "proto.payload", "message": "bad callback"}
    )
    with pytest.raises(MaxApiError) as info:
        await client.answer_callback("cb", notification="ok")
    assert info.value.status == 400
    assert info.value.code == "proto.payload"


@respx.mock
async def test_upload_image_returns_photo_token(client: MaxClient) -> None:
    respx.post(f"{BASE}/uploads").respond(json={"url": "https://upload.test/u1"})
    upload = respx.post("https://upload.test/u1").respond(
        json={"photos": {"p1": {"token": "photo-token"}}}
    )
    token = await client.upload_image(b"png-bytes")
    assert token == "photo-token"
    assert "Authorization" not in upload.calls.last.request.headers


@respx.mock
async def test_download_enforces_size_limit(client: MaxClient) -> None:
    respx.get("https://cdn.test/big.jpg").respond(content=b"x" * 2048)
    with pytest.raises(MaxApiError):
        await client.download("https://cdn.test/big.jpg", max_bytes=1024)
