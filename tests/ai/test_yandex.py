import json
from collections.abc import AsyncIterator

import httpx
import orjson
import pytest
import respx

from yasno.ai.http import ProviderHttpError
from yasno.ai.resilience import FallbackChat, ResilientChat, RetryPolicy
from yasno.ai.types import ChatMessage, ProviderError, Role
from yasno.ai.yandex import (
    YandexChat,
    YandexClient,
    YandexEmbedder,
    YandexOcr,
    YandexVision,
    parse_ocr,
)

LLM = "https://llm.test/v1"
OCR = "https://ocr.test/ocr/v1"
FAST = RetryPolicy(attempts=3, timeout=5, base_delay=0)
MESSAGES = [
    ChatMessage(role=Role.SYSTEM, content="ты помощник"),
    ChatMessage(role=Role.USER, content="привет"),
]


def completion(content: str) -> dict[str, object]:
    return {
        "choices": [{"index": 0, "message": {"role": "assistant", "content": content}}],
        "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
    }


@pytest.fixture
async def client() -> AsyncIterator[YandexClient]:
    yc = YandexClient("key", "folder1", llm_url=LLM, ocr_url=OCR, verify=False)
    yield yc
    await yc.aclose()


@respx.mock
async def test_chat_sends_auth_folder_and_schema(client: YandexClient) -> None:
    route = respx.post(f"{LLM}/chat/completions").respond(json=completion('{"a": 1}'))
    schema = {"title": "Answer", "type": "object", "properties": {"a": {"type": "integer"}}}
    text = await YandexChat(client, "yandexgpt").complete(MESSAGES, json_schema=schema)
    assert text == '{"a": 1}'
    request = route.calls.last.request
    assert request.headers["Authorization"] == "Api-Key key"
    assert request.headers["x-folder-id"] == "folder1"
    assert request.headers["x-data-logging-enabled"] == "false"
    body = orjson.loads(request.content)
    assert body["model"] == "gpt://folder1/yandexgpt/latest"
    assert body["messages"][0] == {"role": "system", "content": "ты помощник"}
    assert body["response_format"]["type"] == "json_schema"
    assert body["response_format"]["json_schema"]["name"] == "Answer"
    assert body["response_format"]["json_schema"]["schema"] == schema


@respx.mock
async def test_full_model_uri_is_kept(client: YandexClient) -> None:
    route = respx.post(f"{LLM}/chat/completions").respond(json=completion("ok"))
    await YandexChat(client, "gpt://other/yandexgpt/rc").complete(MESSAGES)
    assert orjson.loads(route.calls.last.request.content)["model"] == "gpt://other/yandexgpt/rc"


@respx.mock
async def test_429_is_retried(client: YandexClient) -> None:
    route = respx.post(f"{LLM}/chat/completions")
    route.side_effect = [
        httpx.Response(429, headers={"Retry-After": "0"}),
        httpx.Response(200, json=completion("ok")),
    ]
    chat = ResilientChat(YandexChat(client, "yandexgpt"), FAST)
    assert await chat.complete(MESSAGES) == "ok"
    assert route.call_count == 2


@respx.mock
async def test_400_is_not_retryable(client: YandexClient) -> None:
    respx.post(f"{LLM}/chat/completions").respond(400, json={"error": "bad"})
    with pytest.raises(ProviderHttpError) as info:
        await YandexChat(client, "yandexgpt").complete(MESSAGES)
    assert info.value.status == 400
    assert not info.value.retryable


@respx.mock
async def test_5xx_falls_back_to_next_provider(client: YandexClient) -> None:
    respx.post(f"{LLM}/chat/completions").respond(503)
    backup = respx.post("https://backup.test/v1/chat/completions").respond(json=completion("b"))
    other = YandexClient("key", "folder2", llm_url="https://backup.test/v1", verify=False)
    chain = FallbackChat(
        [
            ResilientChat(YandexChat(client, "yandexgpt"), FAST),
            ResilientChat(YandexChat(other, "yandexgpt"), FAST),
        ]
    )
    assert await chain.complete(MESSAGES) == "b"
    assert backup.call_count == 1
    await other.aclose()


@respx.mock
async def test_transport_error_is_retryable(client: YandexClient) -> None:
    respx.post(f"{LLM}/chat/completions").mock(side_effect=httpx.ConnectError("boom"))
    with pytest.raises(ProviderError) as info:
        await YandexChat(client, "yandexgpt").complete(MESSAGES)
    assert info.value.retryable


@respx.mock
async def test_vision_sends_image_and_parses_transcription(client: YandexClient) -> None:
    payload = {
        "task": "Реши уравнение",
        "lines": [{"latex": "2x = 4", "confidence": 0.9}, {"latex": "x = 2"}],
    }
    route = respx.post(f"{LLM}/chat/completions").respond(
        json=completion("```json\n" + json.dumps(payload) + "\n```")
    )
    result = await YandexVision(client, "gemma-3-27b-it").transcribe(b"\xff\xd8img", "image/jpeg")
    assert [line.latex for line in result.lines] == ["2x = 4", "x = 2"]
    body = orjson.loads(route.calls.last.request.content)
    assert body["model"] == "gpt://folder1/gemma-3-27b-it/latest"
    parts = body["messages"][0]["content"]
    assert parts[0]["type"] == "text"
    assert parts[1]["image_url"]["url"].startswith("data:image/jpeg;base64,")


@respx.mock
async def test_vision_repairs_malformed_json_once(client: YandexClient) -> None:
    route = respx.post(f"{LLM}/chat/completions")
    route.side_effect = [
        httpx.Response(200, json=completion("Строка 1: 2x = 4")),
        httpx.Response(200, json=completion('{"lines": [{"latex": "2x = 4"}]}')),
    ]
    result = await YandexVision(client, "gemma-3-27b-it").transcribe(b"img", "image/png")
    assert result.lines[0].latex == "2x = 4"
    repair = orjson.loads(route.calls.last.request.content)
    assert repair["messages"][1] == {"role": "assistant", "content": "Строка 1: 2x = 4"}
    assert all(isinstance(m["content"], str) for m in repair["messages"])


@respx.mock
async def test_vision_gives_up_after_failed_repair(client: YandexClient) -> None:
    respx.post(f"{LLM}/chat/completions").respond(json=completion("не json"))
    with pytest.raises(ProviderError) as info:
        await YandexVision(client, "gemma-3-27b-it").transcribe(b"img", "image/png")
    assert not info.value.retryable


OCR_RESPONSE = {
    "result": {
        "textAnnotation": {
            "width": "1000",
            "height": "500",
            "blocks": [
                {
                    "lines": [
                        {
                            "boundingBox": {
                                "vertices": [
                                    {"x": "100", "y": "50"},
                                    {"x": "100", "y": "100"},
                                    {"x": "600", "y": "100"},
                                    {"x": "600", "y": "50"},
                                ]
                            },
                            "text": "2x+3=7",
                        },
                        {"text": "x=2"},
                    ]
                }
            ],
            "fullText": "2x+3=7\nx=2",
        },
        "page": "0",
    }
}


@respx.mock
async def test_ocr_maps_lines_and_normalizes_bboxes(client: YandexClient) -> None:
    route = respx.post(f"{OCR}/recognizeText").respond(json=OCR_RESPONSE)
    result = await YandexOcr(client, "handwritten").recognize(b"img", "image/jpeg")
    assert [line.text for line in result.lines] == ["2x+3=7", "x=2"]
    bbox = result.lines[0].bbox
    assert bbox is not None
    assert (bbox.x, bbox.y, bbox.width, bbox.height) == (0.1, 0.1, 0.5, 0.1)
    assert result.lines[1].bbox is None
    body = orjson.loads(route.calls.last.request.content)
    assert body["model"] == "handwritten"
    assert body["mimeType"] == "image/jpeg"
    assert body["languageCodes"] == ["ru", "en"]
    assert route.calls.last.request.headers["x-folder-id"] == "folder1"


def test_ocr_parses_snake_case_alternatives_and_streams() -> None:
    chunk = {
        "result": {
            "text_annotation": {
                "width": 10,
                "height": 10,
                "blocks": [
                    {
                        "lines": [
                            {
                                "bounding_box": {"vertices": [{"x": 0, "y": 0}, {"x": 20, "y": 5}]},
                                "alternatives": [{"text": "x=1"}],
                            }
                        ]
                    }
                ],
            }
        }
    }
    content = orjson.dumps(chunk) + b"\n" + orjson.dumps(chunk)
    result = parse_ocr(content)
    assert result.lines[0].text == "x=1"
    assert result.lines[0].bbox is not None
    assert result.lines[0].bbox.width == 1.0


def test_ocr_falls_back_to_full_text() -> None:
    result = parse_ocr(orjson.dumps({"textAnnotation": {"markdown": "# x\n\ny = 2"}}))
    assert result.text == "# x\ny = 2"


@respx.mock
async def test_embeddings_use_doc_and_query_models(client: YandexClient) -> None:
    route = respx.post(f"{LLM}/embeddings").respond(
        json={"data": [{"index": 0, "embedding": [0.1, 0.2]}], "usage": {"prompt_tokens": 2}}
    )
    embedder = YandexEmbedder(client, dimensions=2)
    vectors = await embedder.embed(["a", "b"], kind="document")
    assert vectors == [[0.1, 0.2], [0.1, 0.2]]
    assert orjson.loads(route.calls.last.request.content)["model"] == (
        "emb://folder1/text-search-doc/latest"
    )
    await embedder.embed(["q"], kind="query")
    assert orjson.loads(route.calls.last.request.content) == {
        "model": "emb://folder1/text-search-query/latest",
        "input": ["q"],
    }
