import ssl
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field

import httpx
import structlog
from pydantic import SecretStr

from yasno.ai.fakes import FakeChat, FakeEmbedder, FakeOcr, FakeVision
from yasno.ai.gigachat import GigaChatChat, GigaChatClient, GigaChatVision
from yasno.ai.openai_compat import OpenAICompatChat, OpenAICompatClient, OpenAICompatVision
from yasno.ai.resilience import (
    FallbackChat,
    FallbackVision,
    ResilientChat,
    ResilientEmbedder,
    ResilientOcr,
    ResilientVision,
    RetryPolicy,
)
from yasno.ai.types import ChatModel, Embedder, OcrEngine, VisionModel
from yasno.ai.yandex import YandexChat, YandexClient, YandexEmbedder, YandexOcr, YandexVision
from yasno.config import Settings
from yasno.max.tls import build_ssl_context

log = structlog.get_logger(__name__)

KNOWN_PROVIDERS = ("yandex", "gigachat", "openai")


class AiConfigurationError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class ProviderSet:
    name: str
    chat: ChatModel
    vision: VisionModel | None
    ocr: OcrEngine | None = None
    embedder: Embedder | None = None
    close: Callable[[], Awaitable[None]] | None = None


@dataclass
class AiServices:
    vision: VisionModel
    chat: ChatModel
    ocr: OcrEngine | None
    embedder: Embedder | None
    providers: list[ProviderSet] = field(default_factory=list)

    async def aclose(self) -> None:
        for provider in self.providers:
            if provider.close is not None:
                await provider.close()


def _missing(settings: Settings, name: str) -> list[str]:
    if name == "yandex":
        return [
            env
            for env, value in (
                ("YANDEX_API_KEY", settings.yandex_api_key),
                ("YANDEX_FOLDER_ID", settings.yandex_folder_id),
            )
            if not value
        ]
    if name == "gigachat":
        return [] if settings.gigachat_credentials else ["GIGACHAT_CREDENTIALS"]
    return []


def _yandex(
    settings: Settings,
    transport: httpx.AsyncBaseTransport | None,
    verify: ssl.SSLContext | bool,
) -> ProviderSet:
    assert settings.yandex_api_key is not None
    assert settings.yandex_folder_id is not None
    client = YandexClient(
        settings.yandex_api_key.get_secret_value(),
        settings.yandex_folder_id,
        llm_url=str(settings.yandex_llm_url),
        ocr_url=str(settings.yandex_ocr_url),
        timeout=settings.ai_timeout_seconds,
        transport=transport,
        verify=verify,
    )
    return ProviderSet(
        name="yandex",
        chat=YandexChat(client, settings.yandex_chat_model),
        vision=YandexVision(client, settings.yandex_vision_model),
        ocr=YandexOcr(client, settings.yandex_ocr_model),
        embedder=YandexEmbedder(
            client,
            doc_model=settings.yandex_embedding_doc_model,
            query_model=settings.yandex_embedding_query_model,
            dimensions=settings.yandex_embedding_dimensions,
        ),
        close=client.aclose,
    )


def _gigachat(
    settings: Settings,
    transport: httpx.AsyncBaseTransport | None,
    verify: ssl.SSLContext | bool,
) -> ProviderSet:
    assert settings.gigachat_credentials is not None
    client = GigaChatClient(
        settings.gigachat_credentials.get_secret_value(),
        scope=settings.gigachat_scope,
        base_url=str(settings.gigachat_base_url),
        auth_url=str(settings.gigachat_auth_url),
        timeout=settings.ai_timeout_seconds,
        transport=transport,
        verify=verify,
    )
    return ProviderSet(
        name="gigachat",
        chat=GigaChatChat(client, settings.gigachat_model),
        vision=GigaChatVision(client, settings.gigachat_vision_model or settings.gigachat_model),
        close=client.aclose,
    )


def _secret(value: SecretStr | None) -> str | None:
    return value.get_secret_value() if value else None


def _openai(
    settings: Settings,
    transport: httpx.AsyncBaseTransport | None,
    verify: ssl.SSLContext | bool,
) -> ProviderSet:
    def client(url: str, key: str | None) -> OpenAICompatClient:
        return OpenAICompatClient(
            url,
            key,
            json_mode=settings.openai_json_mode,
            timeout=settings.ai_timeout_seconds,
            transport=transport,
            verify=verify,
        )

    chat_client = client(str(settings.openai_base_url), _secret(settings.openai_api_key))
    clients = [chat_client]
    vision = None
    if settings.openai_vision_model:
        vision_client = chat_client
        if settings.openai_vision_base_url is not None:
            vision_client = client(
                str(settings.openai_vision_base_url),
                _secret(settings.openai_vision_api_key or settings.openai_api_key),
            )
            clients.append(vision_client)
        vision = OpenAICompatVision(vision_client, settings.openai_vision_model)

    async def close() -> None:
        for item in clients:
            await item.aclose()

    return ProviderSet(
        name="openai",
        chat=OpenAICompatChat(chat_client, settings.openai_chat_model),
        vision=vision,
        close=close,
    )


def build_provider_sets(
    settings: Settings,
    *,
    transport: httpx.AsyncBaseTransport | None = None,
    verify: ssl.SSLContext | bool | None = None,
) -> list[ProviderSet]:
    order = settings.ai_providers
    if not order:
        raise AiConfigurationError("AI_PROVIDER_ORDER is empty: use e.g. 'yandex,gigachat'")
    unknown = [name for name in order if name not in KNOWN_PROVIDERS]
    if unknown:
        raise AiConfigurationError(
            f"unknown AI providers {unknown} in AI_PROVIDER_ORDER, known: {list(KNOWN_PROVIDERS)}"
        )
    missing = {name: _missing(settings, name) for name in order}
    problems = [f"{name}: {', '.join(envs)}" for name, envs in missing.items() if envs]
    if problems:
        raise AiConfigurationError(
            "missing credentials for AI providers ("
            + "; ".join(problems)
            + "); set them, remove the provider from AI_PROVIDER_ORDER or set AI_FAKE=true"
        )
    context = verify if verify is not None else build_ssl_context()
    builders = {"yandex": _yandex, "gigachat": _gigachat, "openai": _openai}
    return [builders[name](settings, transport, context) for name in dict.fromkeys(order)]


def build_ai(
    settings: Settings,
    *,
    transport: httpx.AsyncBaseTransport | None = None,
    verify: ssl.SSLContext | bool | None = None,
) -> AiServices:
    if settings.ai_fake:
        log.info("ai_services_built", mode="fake")
        return AiServices(
            vision=FakeVision(), chat=FakeChat(), ocr=FakeOcr(), embedder=FakeEmbedder()
        )
    sets = build_provider_sets(settings, transport=transport, verify=verify)
    policy = RetryPolicy(attempts=settings.ai_max_attempts, timeout=settings.ai_timeout_seconds)
    chat = FallbackChat(
        [ResilientChat(item.chat, policy) for item in sets],
        failures=settings.ai_breaker_failures,
        cooldown=settings.ai_breaker_cooldown_seconds,
    )
    readers = [item.vision for item in sets if item.vision is not None]
    if not readers:
        raise AiConfigurationError(
            "no AI provider can read photos: set OPENAI_VISION_MODEL or add yandex/gigachat"
        )
    vision = FallbackVision(
        [ResilientVision(reader, policy) for reader in readers],
        failures=settings.ai_breaker_failures,
        cooldown=settings.ai_breaker_cooldown_seconds,
    )
    ocr_engine = next((item.ocr for item in sets if item.ocr is not None), None)
    ocr = ResilientOcr(ocr_engine, policy) if ocr_engine and settings.ai_ocr_enabled else None
    embedder_model = next((item.embedder for item in sets if item.embedder is not None), None)
    embedder = ResilientEmbedder(embedder_model, policy) if embedder_model else None
    log.info(
        "ai_services_built",
        mode="live",
        chat=chat.name,
        vision=vision.name,
        ocr=ocr.name if ocr else None,
        embedder=embedder.name if embedder else None,
    )
    return AiServices(vision=vision, chat=chat, ocr=ocr, embedder=embedder, providers=sets)
