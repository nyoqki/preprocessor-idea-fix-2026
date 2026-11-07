from enum import StrEnum
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import AnyHttpUrl, Field, PostgresDsn, RedisDsn, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Environment(StrEnum):
    DEVELOPMENT = "development"
    PRODUCTION = "production"
    TEST = "test"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    environment: Environment = Environment.DEVELOPMENT
    log_level: str = "INFO"
    log_json: bool = True

    max_bot_token: SecretStr
    max_api_url: AnyHttpUrl = AnyHttpUrl("https://platform-api2.max.ru")
    max_webhook_secret: SecretStr | None = None
    max_extra_ca_file: Path | None = None

    public_base_url: AnyHttpUrl | None = None

    database_url: PostgresDsn = PostgresDsn("postgresql+asyncpg://yasno:yasno@localhost:5432/yasno")
    redis_url: RedisDsn = RedisDsn("redis://localhost:6379/0")
    database_pool_size: int = Field(default=10, ge=1)
    database_max_overflow: int = Field(default=10, ge=0)
    worker_max_jobs: int = Field(default=20, ge=1)
    math_workers: int = Field(default=2, ge=1)

    storage_dir: Path = Path("data/storage")

    webapp_dist_dir: Path = Path("webapp/dist")
    webapp_init_data_ttl_seconds: int = Field(default=86400, gt=0)

    timezone: str = "Europe/Moscow"

    ai_provider_order: str = "yandex,gigachat"
    ai_fake: bool = False
    ai_timeout_seconds: float = Field(default=60.0, gt=0)
    ai_max_attempts: int = Field(default=3, ge=1)
    ai_breaker_failures: int = Field(default=3, ge=1)
    ai_breaker_cooldown_seconds: float = Field(default=60.0, ge=0)
    ai_ocr_enabled: bool = True

    yandex_api_key: SecretStr | None = None
    yandex_folder_id: str | None = None
    yandex_llm_url: AnyHttpUrl = AnyHttpUrl("https://llm.api.cloud.yandex.net/v1")
    yandex_ocr_url: AnyHttpUrl = AnyHttpUrl("https://ocr.api.cloud.yandex.net/ocr/v1")
    yandex_chat_model: str = "yandexgpt"
    yandex_vision_model: str = "gemma-3-27b-it"
    yandex_ocr_model: str = "handwritten"
    yandex_embedding_doc_model: str = "text-search-doc"
    yandex_embedding_query_model: str = "text-search-query"
    yandex_embedding_dimensions: int = Field(default=256, gt=0)

    gigachat_credentials: SecretStr | None = None
    gigachat_scope: str = "GIGACHAT_API_PERS"
    gigachat_model: str = "GigaChat-2-Max"
    gigachat_vision_model: str | None = None
    gigachat_base_url: AnyHttpUrl = AnyHttpUrl("https://api.giga.chat/v1")
    gigachat_auth_url: AnyHttpUrl = AnyHttpUrl("https://ngw.devices.sberbank.ru:9443/api/v2/oauth")

    openai_base_url: AnyHttpUrl = AnyHttpUrl("https://api.deepseek.com/v1")
    openai_api_key: SecretStr | None = None
    openai_chat_model: str = "deepseek-v4-flash"
    openai_json_mode: Literal["schema", "object", "off"] = "object"
    openai_reasoning_tokens: int = Field(default=0, ge=0)
    openai_vision_thinking: bool | None = None
    openai_vision_model: str | None = None
    openai_vision_base_url: AnyHttpUrl | None = None
    openai_vision_api_key: SecretStr | None = None

    @property
    def ai_providers(self) -> list[str]:
        return [p.strip().lower() for p in self.ai_provider_order.split(",") if p.strip()]

    @property
    def webhook_path(self) -> str:
        return "/webhook/max"


@lru_cache
def get_settings() -> Settings:
    return Settings()
