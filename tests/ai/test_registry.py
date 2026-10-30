from typing import Any

import pytest
import respx

from yasno.ai.fakes import FakeChat, FakeEmbedder, FakeOcr, FakeVision
from yasno.ai.registry import AiConfigurationError, build_ai
from yasno.ai.resilience import FallbackChat, FallbackVision
from yasno.ai.types import ChatMessage, Role
from yasno.config import Settings


def settings(**values: Any) -> Settings:
    base: dict[str, Any] = {"max_bot_token": "t", "ai_max_attempts": 1}
    return Settings(_env_file=None, **(base | values))


def test_fake_mode_gives_fakes() -> None:
    services = build_ai(settings(ai_fake=True))
    assert isinstance(services.chat, FakeChat)
    assert isinstance(services.vision, FakeVision)
    assert isinstance(services.ocr, FakeOcr)
    assert isinstance(services.embedder, FakeEmbedder)


def test_missing_keys_are_reported_clearly() -> None:
    with pytest.raises(AiConfigurationError) as info:
        build_ai(settings(yandex_api_key="k"))
    message = str(info.value)
    assert "YANDEX_FOLDER_ID" in message
    assert "GIGACHAT_CREDENTIALS" in message
    assert "AI_FAKE" in message


def test_unknown_provider_is_rejected() -> None:
    with pytest.raises(AiConfigurationError, match="openai"):
        build_ai(settings(ai_provider_order="yandex,openai"))


async def test_builds_chain_in_configured_order() -> None:
    services = build_ai(
        settings(
            ai_provider_order="gigachat,yandex",
            yandex_api_key="k",
            yandex_folder_id="f",
            gigachat_credentials="c",
        ),
        verify=False,
    )
    assert isinstance(services.chat, FallbackChat)
    assert isinstance(services.vision, FallbackVision)
    assert services.chat.name.startswith("gigachat:GigaChat-2-Max > yandex:yandexgpt")
    assert services.vision.name == "gigachat:GigaChat-2-Max > yandex:gemma-3-27b-it"
    assert services.ocr is not None
    assert services.ocr.name == "yandex:ocr-handwritten"
    assert services.embedder is not None
    assert services.embedder.dimensions == 256
    await services.aclose()


async def test_gigachat_only_has_no_ocr_or_embedder() -> None:
    services = build_ai(
        settings(ai_provider_order="gigachat", gigachat_credentials="c"), verify=False
    )
    assert services.ocr is None
    assert services.embedder is None
    await services.aclose()


@respx.mock
async def test_live_chain_falls_back_from_yandex_to_gigachat() -> None:
    respx.post("https://llm.api.cloud.yandex.net/v1/chat/completions").respond(500)
    respx.post("https://ngw.devices.sberbank.ru:9443/api/v2/oauth").respond(
        json={"access_token": "t", "expires_at": 4_102_444_800_000}
    )
    respx.post("https://api.giga.chat/v1/chat/completions").respond(
        json={"choices": [{"message": {"role": "assistant", "content": "из гигачата"}}]}
    )
    services = build_ai(
        settings(yandex_api_key="k", yandex_folder_id="f", gigachat_credentials="c"),
        verify=False,
    )
    answer = await services.chat.complete([ChatMessage(role=Role.USER, content="привет")])
    assert answer == "из гигачата"
    await services.aclose()
