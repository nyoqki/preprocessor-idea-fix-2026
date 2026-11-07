from collections.abc import AsyncIterator
from typing import Any

import orjson
import pytest
import respx

from yasno.ai.http import ProviderHttpError
from yasno.ai.openai_compat import OpenAICompatChat, OpenAICompatClient, OpenAICompatVision
from yasno.ai.registry import AiConfigurationError, build_ai
from yasno.ai.resilience import FallbackChat
from yasno.ai.types import ChatMessage, Role
from yasno.config import Settings

BASE = "https://llm.test/v1"
SCHEMA = {"title": "Answer", "type": "object", "properties": {"a": {"type": "integer"}}}
MESSAGES = [ChatMessage(role=Role.USER, content="ответь в JSON")]


def completion(content: str) -> dict[str, object]:
    return {"choices": [{"index": 0, "message": {"role": "assistant", "content": content}}]}


def settings(**values: Any) -> Settings:
    base: dict[str, Any] = {"max_bot_token": "t", "ai_max_attempts": 1}
    return Settings(_env_file=None, **(base | values))


@pytest.fixture
async def client() -> AsyncIterator[OpenAICompatClient]:
    item = OpenAICompatClient(BASE, "sk-test", verify=False)
    yield item
    await item.aclose()


@respx.mock
async def test_chat_uses_bearer_key_and_json_object(client: OpenAICompatClient) -> None:
    route = respx.post(f"{BASE}/chat/completions").respond(json=completion('{"a": 1}'))
    text = await OpenAICompatChat(client, "deepseek-v4-flash").complete(
        MESSAGES, json_schema=SCHEMA
    )
    assert text == '{"a": 1}'
    request = route.calls.last.request
    assert request.headers["Authorization"] == "Bearer sk-test"
    body = orjson.loads(request.content)
    assert body["model"] == "deepseek-v4-flash"
    assert body["response_format"] == {"type": "json_object"}


@respx.mock
async def test_schema_mode_and_keyless_local_server() -> None:
    local = OpenAICompatClient("http://localhost:11434/v1", None, json_mode="schema")
    route = respx.post("http://localhost:11434/v1/chat/completions").respond(
        json=completion('{"a": 2}')
    )
    await OpenAICompatChat(local, "qwen3:8b").complete(MESSAGES, json_schema=SCHEMA)
    await local.aclose()
    request = route.calls.last.request
    assert "Authorization" not in request.headers
    body = orjson.loads(request.content)
    assert body["response_format"]["json_schema"]["schema"] == SCHEMA


@respx.mock
async def test_off_mode_sends_no_response_format() -> None:
    plain = OpenAICompatClient(BASE, "k", json_mode="off", verify=False)
    route = respx.post(f"{BASE}/chat/completions").respond(json=completion("{}"))
    await OpenAICompatChat(plain, "m").complete(MESSAGES, json_schema=SCHEMA)
    await plain.aclose()
    assert "response_format" not in orjson.loads(route.calls.last.request.content)


@respx.mock
async def test_chat_keeps_thinking_and_reserves_reasoning_tokens(
    client: OpenAICompatClient,
) -> None:
    route = respx.post(f"{BASE}/chat/completions").respond(json=completion("ok"))
    await OpenAICompatChat(client, "m", reasoning_tokens=4000).complete(MESSAGES, max_tokens=600)
    body = orjson.loads(route.calls.last.request.content)
    assert "thinking" not in body
    assert body["max_tokens"] == 4600


@respx.mock
async def test_vision_can_disable_thinking(client: OpenAICompatClient) -> None:
    route = respx.post(f"{BASE}/chat/completions").respond(
        json=completion('{"is_math": true, "lines": [{"latex": "x = 1"}]}')
    )
    await OpenAICompatVision(client, "m", thinking=False).transcribe(b"\x89PNG", "image/png")
    assert orjson.loads(route.calls.last.request.content)["thinking"] == {"type": "disabled"}


@respx.mock
async def test_answer_cut_by_token_limit_is_not_retried(client: OpenAICompatClient) -> None:
    payload = completion("")
    payload["choices"][0]["finish_reason"] = "length"  # type: ignore[index]
    respx.post(f"{BASE}/chat/completions").respond(json=payload)
    with pytest.raises(ProviderHttpError, match="max_tokens") as caught:
        await OpenAICompatChat(client, "m").complete(MESSAGES)
    assert not caught.value.retryable


@respx.mock
async def test_vision_sends_data_url(client: OpenAICompatClient) -> None:
    payload = orjson.dumps({"is_math": True, "lines": [{"index": 1, "latex": "x=1"}]}).decode()
    route = respx.post(f"{BASE}/chat/completions").respond(json=completion(payload))
    result = await OpenAICompatVision(client, "qwen2.5-vl").transcribe(b"\x89PNG", "image/png")
    assert [line.latex for line in result.lines] == ["x=1"]
    content = orjson.loads(route.calls.last.request.content)["messages"][0]["content"]
    assert content[1]["image_url"]["url"].startswith("data:image/png;base64,")


async def test_registry_requires_a_photo_reader() -> None:
    with pytest.raises(AiConfigurationError, match="OPENAI_VISION_MODEL"):
        build_ai(settings(ai_provider_order="openai", openai_api_key="k"), verify=False)


async def test_registry_builds_split_chat_and_vision_endpoints() -> None:
    services = build_ai(
        settings(
            ai_provider_order="openai",
            openai_api_key="k",
            openai_vision_model="qwen/qwen2.5-vl-72b-instruct",
            openai_vision_base_url="https://openrouter.test/api/v1",
            openai_vision_api_key="or",
        ),
        verify=False,
    )
    assert isinstance(services.chat, FallbackChat)
    assert services.chat.name.startswith("openai:deepseek-v4-flash")
    assert services.vision is not None
    assert services.vision.name == "openai:qwen/qwen2.5-vl-72b-instruct"
    assert services.ocr is None
    assert services.embedder is None
    await services.aclose()
