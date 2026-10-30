import argparse
import asyncio
import sys
from collections.abc import Sequence

from yasno.config import Settings, get_settings
from yasno.logs import configure_logging
from yasno.max.client import MaxClient
from yasno.max.types import UpdateType

WEBHOOK_UPDATE_TYPES = [
    UpdateType.MESSAGE_CREATED,
    UpdateType.MESSAGE_CALLBACK,
    UpdateType.MESSAGE_EDITED,
    UpdateType.BOT_STARTED,
    UpdateType.BOT_STOPPED,
    UpdateType.BOT_ADDED,
    UpdateType.BOT_REMOVED,
    UpdateType.USER_ADDED,
    UpdateType.USER_REMOVED,
    UpdateType.CHAT_TITLE_CHANGED,
]


def _client(settings: Settings) -> MaxClient:
    return MaxClient(
        settings.max_bot_token.get_secret_value(),
        base_url=str(settings.max_api_url).rstrip("/"),
    )


def run_api(host: str, port: int) -> None:
    import uvicorn

    uvicorn.run(
        "yasno.api.app:create_app",
        factory=True,
        host=host,
        port=port,
        proxy_headers=True,
        forwarded_allow_ips="*",
        log_config=None,
    )


def run_worker() -> None:
    from arq import run_worker as arq_run_worker

    from yasno.worker.app import WorkerSettings

    arq_run_worker(WorkerSettings)  # type: ignore[arg-type]


def run_poll(settings: Settings) -> None:
    from yasno.polling import run_polling

    asyncio.run(run_polling(settings))


def run_migrate(revision: str) -> None:
    from alembic import command
    from alembic.config import Config

    from yasno.db.migrations import alembic_config

    config: Config = alembic_config()
    command.upgrade(config, revision)


async def webhook_set(settings: Settings) -> None:
    if settings.public_base_url is None:
        raise SystemExit("PUBLIC_BASE_URL is required to register a webhook")
    url = str(settings.public_base_url).rstrip("/") + settings.webhook_path
    secret = settings.max_webhook_secret.get_secret_value() if settings.max_webhook_secret else None
    async with _client(settings) as client:
        await client.subscribe(url, secret=secret, update_types=WEBHOOK_UPDATE_TYPES)
    print(f"webhook registered: {url}")


async def webhook_delete(settings: Settings) -> None:
    async with _client(settings) as client:
        for subscription in (await client.get_subscriptions()).subscriptions:
            await client.unsubscribe(subscription.url)
            print(f"webhook removed: {subscription.url}")


async def webhook_info(settings: Settings) -> None:
    async with _client(settings) as client:
        me = await client.get_me()
        print(f"bot: {me.username} ({me.user_id})")
        for subscription in (await client.get_subscriptions()).subscriptions:
            print(f"webhook: {subscription.url} types={subscription.update_types}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="yasno")
    sub = parser.add_subparsers(dest="command", required=True)

    api = sub.add_parser("api")
    api.add_argument("--host", default="0.0.0.0")  # noqa: S104
    api.add_argument("--port", type=int, default=8000)

    sub.add_parser("worker")
    sub.add_parser("poll")

    migrate = sub.add_parser("migrate")
    migrate.add_argument("revision", nargs="?", default="head")

    webhook = sub.add_parser("webhook")
    webhook.add_argument("action", choices=["set", "delete", "info"])
    return parser


def main(argv: Sequence[str] | None = None) -> None:
    args = build_parser().parse_args(argv)
    settings = get_settings()
    configure_logging(settings.log_level, json=settings.log_json)

    match args.command:
        case "api":
            run_api(args.host, args.port)
        case "worker":
            run_worker()
        case "poll":
            run_poll(settings)
        case "migrate":
            run_migrate(args.revision)
        case "webhook":
            actions = {"set": webhook_set, "delete": webhook_delete, "info": webhook_info}
            asyncio.run(actions[args.action](settings))
        case _:
            sys.exit(2)
