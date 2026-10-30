from collections.abc import Iterable, Sequence
from typing import Any

type Button = dict[str, Any]
type AttachmentRequest = dict[str, Any]


def callback(text: str, payload: str) -> Button:
    return {"type": "callback", "text": text, "payload": payload}


def link(text: str, url: str) -> Button:
    return {"type": "link", "text": text, "url": url}


def message(text: str) -> Button:
    return {"type": "message", "text": text}


def open_app(text: str, bot_username: str, payload: str | None = None) -> Button:
    button: Button = {"type": "open_app", "text": text, "web_app": bot_username}
    if payload:
        button["payload"] = payload
    return button


def inline_keyboard(rows: Iterable[Sequence[Button]]) -> AttachmentRequest:
    buttons = [list(row) for row in rows if row]
    return {"type": "inline_keyboard", "payload": {"buttons": buttons}}


def image(token: str) -> AttachmentRequest:
    return {"type": "image", "payload": {"token": token}}


def image_url(url: str) -> AttachmentRequest:
    return {"type": "image", "payload": {"url": url}}
