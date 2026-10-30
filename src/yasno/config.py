from enum import StrEnum
from functools import lru_cache
from pathlib import Path

from pydantic import AnyHttpUrl, Field, PostgresDsn, RedisDsn, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Environment(StrEnum):
    DEVELOPMENT = "development"
    PRODUCTION = "production"
    TEST = "test"


class UpdatesMode(StrEnum):
    WEBHOOK = "webhook"
    POLLING = "polling"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    environment: Environment = Environment.DEVELOPMENT
    log_level: str = "INFO"
    log_json: bool = True

    max_bot_token: SecretStr
    max_api_url: AnyHttpUrl = AnyHttpUrl("https://platform-api2.max.ru")
    max_webhook_secret: SecretStr | None = None
    max_extra_ca_file: Path | None = None
    updates_mode: UpdatesMode = UpdatesMode.WEBHOOK

    public_base_url: AnyHttpUrl | None = None

    database_url: PostgresDsn = PostgresDsn("postgresql+asyncpg://yasno:yasno@localhost:5432/yasno")
    redis_url: RedisDsn = RedisDsn("redis://localhost:6379/0")

    storage_dir: Path = Path("data/storage")

    webapp_dist_dir: Path = Path("webapp/dist")
    webapp_init_data_ttl_seconds: int = Field(default=86400, gt=0)

    timezone: str = "Europe/Moscow"

    @property
    def webhook_path(self) -> str:
        return "/webhook/max"


@lru_cache
def get_settings() -> Settings:
    return Settings()
