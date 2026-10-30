from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, cast

from pydantic import SecretStr
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from yasno.ai.fakes import FakeChat, FakeVision
from yasno.ai.tutor import Tutor
from yasno.bot.app import build_router
from yasno.bot.context import BotContext
from yasno.config import Settings
from yasno.max.client import MaxClient
from yasno.max.types import ChatMember, ChatType, Message, MessageBody, Recipient, Update
from yasno.storage import LocalStorage


@dataclass
class Sent:
    user_id: int | None
    chat_id: int | None
    text: str | None
    attachments: list[dict[str, Any]] | None


@dataclass
class FakeMax:
    sent: list[Sent] = field(default_factory=list)
    callbacks: list[dict[str, Any]] = field(default_factory=list)
    permissions: list[str] = field(default_factory=lambda: ["read_all_messages", "write"])
    chat_title: str = "9Б класс"
    image: bytes = b"\xff\xd8\xff\xe0fake-jpeg"
    downloads: list[str] = field(default_factory=list)

    async def send_message(
        self,
        *,
        user_id: int | None = None,
        chat_id: int | None = None,
        text: str | None = None,
        attachments: list[dict[str, Any]] | None = None,
        **_: Any,
    ) -> Message:
        self.sent.append(Sent(user_id, chat_id, text, attachments))
        return Message(
            recipient=Recipient(chat_type=ChatType.DIALOG, user_id=user_id, chat_id=chat_id),
            timestamp=1,
            body=MessageBody(mid=f"m{len(self.sent)}", text=text),
        )

    async def answer_callback(self, callback_id: str, **kwargs: Any) -> None:
        self.callbacks.append({"callback_id": callback_id, **kwargs})

    async def send_action(self, chat_id: int, action: str = "typing_on") -> None:
        return None

    async def get_chat(self, chat_id: int) -> Any:
        return type("Chat", (), {"title": self.chat_title})()

    async def get_my_membership(self, chat_id: int) -> ChatMember:
        return ChatMember(user_id=1, first_name="bot", is_bot=True, permissions=self.permissions)

    async def download(self, url: str, **_: Any) -> bytes:
        self.downloads.append(url)
        return self.image

    def texts_to(self, user_id: int) -> list[str]:
        return [s.text or "" for s in self.sent if s.user_id == user_id]

    def buttons(self, index: int = -1) -> list[dict[str, Any]]:
        attachments = self.sent[index].attachments or []
        rows = attachments[0]["payload"]["buttons"] if attachments else []
        return [button for row in rows for button in row]


class FakeRedis:
    def __init__(self) -> None:
        self.values: dict[str, int] = {}

    async def incr(self, key: str) -> int:
        self.values[key] = self.values.get(key, 0) + 1
        return self.values[key]

    async def expire(self, key: str, seconds: int) -> bool:
        return True


@dataclass
class Harness:
    ctx: BotContext
    max: FakeMax
    chat: FakeChat

    async def feed(self, raw: dict[str, Any]) -> bool:
        return await build_router().dispatch(Update.model_validate(raw), self.ctx)


def make_harness(sessions: async_sessionmaker[AsyncSession], tmp_path: Path) -> Harness:
    fake_max = FakeMax()
    chat = FakeChat()
    ctx = BotContext(
        settings=Settings(max_bot_token=SecretStr("bot-token"), storage_dir=tmp_path),
        max=cast(MaxClient, fake_max),
        sessions=sessions,
        redis=cast(Any, FakeRedis()),
        tutor=Tutor(chat, FakeVision()),
        storage=LocalStorage(tmp_path),
        bot_username="yasno_bot",
    )
    return Harness(ctx, fake_max, chat)
