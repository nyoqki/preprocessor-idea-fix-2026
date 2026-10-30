from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class MaxModel(BaseModel):
    model_config = ConfigDict(extra="ignore", populate_by_name=True)


class UpdateType(StrEnum):
    MESSAGE_CREATED = "message_created"
    MESSAGE_CALLBACK = "message_callback"
    MESSAGE_EDITED = "message_edited"
    MESSAGE_REMOVED = "message_removed"
    BOT_STARTED = "bot_started"
    BOT_STOPPED = "bot_stopped"
    BOT_ADDED = "bot_added"
    BOT_REMOVED = "bot_removed"
    USER_ADDED = "user_added"
    USER_REMOVED = "user_removed"
    CHAT_TITLE_CHANGED = "chat_title_changed"
    DIALOG_CLEARED = "dialog_cleared"
    DIALOG_REMOVED = "dialog_removed"


class ChatType(StrEnum):
    DIALOG = "dialog"
    CHAT = "chat"
    CHANNEL = "channel"


class TextFormat(StrEnum):
    MARKDOWN = "markdown"
    HTML = "html"


class User(MaxModel):
    user_id: int
    first_name: str = ""
    last_name: str | None = None
    username: str | None = None
    is_bot: bool = False

    @property
    def full_name(self) -> str:
        return " ".join(part for part in (self.first_name, self.last_name) if part)


class BotInfo(User):
    name: str | None = None
    description: str | None = None


class Recipient(MaxModel):
    chat_id: int | None = None
    chat_type: ChatType
    user_id: int | None = None


class Attachment(MaxModel):
    type: str
    payload: dict[str, Any] | None = None
    filename: str | None = None
    size: int | None = None

    @property
    def url(self) -> str | None:
        if self.payload is None:
            return None
        value = self.payload.get("url")
        return value if isinstance(value, str) else None

    @property
    def token(self) -> str | None:
        if self.payload is None:
            return None
        value = self.payload.get("token")
        return value if isinstance(value, str) else None


class MessageBody(MaxModel):
    mid: str
    seq: int = 0
    text: str | None = None
    attachments: list[Attachment] | None = None

    def attachments_of(self, kind: str) -> list[Attachment]:
        return [a for a in self.attachments or [] if a.type == kind]


class LinkedMessage(MaxModel):
    type: Literal["forward", "reply"]
    sender: User | None = None
    chat_id: int | None = None
    message: MessageBody


class Message(MaxModel):
    sender: User | None = None
    recipient: Recipient
    timestamp: int
    body: MessageBody
    link: LinkedMessage | None = None

    @property
    def chat_id(self) -> int | None:
        return self.recipient.chat_id

    @property
    def is_dialog(self) -> bool:
        return self.recipient.chat_type is ChatType.DIALOG

    @property
    def text(self) -> str:
        return (self.body.text or "").strip()

    def all_attachments(self) -> list[Attachment]:
        items = list(self.body.attachments or [])
        if self.link is not None:
            items.extend(self.link.message.attachments or [])
        return items


class Callback(MaxModel):
    timestamp: int
    callback_id: str
    payload: str | None = None
    user: User


class Update(MaxModel):
    update_type: str
    timestamp: int
    message: Message | None = None
    callback: Callback | None = None
    chat_id: int | None = None
    user: User | None = None
    payload: str | None = None
    user_locale: str | None = None
    is_channel: bool | None = None
    inviter_id: int | None = None
    message_id: str | None = None

    @property
    def kind(self) -> UpdateType | None:
        try:
            return UpdateType(self.update_type)
        except ValueError:
            return None

    @property
    def actor(self) -> User | None:
        if self.callback is not None:
            return self.callback.user
        if self.message is not None and self.message.sender is not None:
            return self.message.sender
        return self.user

    def dedup_key(self) -> str:
        if self.callback is not None:
            return f"cb:{self.callback.callback_id}"
        if self.message is not None:
            return f"{self.update_type}:{self.message.body.mid}"
        return f"{self.update_type}:{self.chat_id}:{self.actor_id}:{self.timestamp}"

    @property
    def actor_id(self) -> int | None:
        actor = self.actor
        return actor.user_id if actor is not None else None


class UpdateList(MaxModel):
    updates: list[Update] = Field(default_factory=list)
    marker: int | None = None


class UploadEndpoint(MaxModel):
    url: str
    token: str | None = None


class SendMessageResult(MaxModel):
    message: Message


class Subscription(MaxModel):
    url: str
    time: int | None = None
    update_types: list[str] | None = None


class Subscriptions(MaxModel):
    subscriptions: list[Subscription] = Field(default_factory=list)


class ChatMember(User):
    is_admin: bool = False
    is_owner: bool = False
    permissions: list[str] | None = None


class ChatMembers(MaxModel):
    members: list[ChatMember] = Field(default_factory=list)
    marker: int | None = None


class Chat(MaxModel):
    chat_id: int
    type: ChatType
    status: str | None = None
    title: str | None = None
    participants_count: int | None = None
