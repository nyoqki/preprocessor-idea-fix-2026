import pytest
from pydantic import SecretStr

from yasno.cli import webhook_set
from yasno.config import Environment, Settings


@pytest.mark.parametrize(
    ("url", "secret", "message"),
    [
        ("https://yasno.example.ru", None, "MAX_WEBHOOK_SECRET"),
        ("http://yasno.example.ru", SecretStr("secret"), "HTTPS"),
    ],
)
async def test_production_webhook_requires_secret_and_https(
    url: str, secret: SecretStr | None, message: str
) -> None:
    settings = Settings(
        _env_file=None,
        max_bot_token="t",
        environment=Environment.PRODUCTION,
        public_base_url=url,
        max_webhook_secret=secret,
    )
    with pytest.raises(SystemExit, match=message):
        await webhook_set(settings)
