from typing import Any


def user(user_id: int = 100, first_name: str = "Аня") -> dict[str, Any]:
    return {"user_id": user_id, "first_name": first_name, "is_bot": False}


def dialog_message(
    text: str | None = "привет",
    *,
    user_id: int = 100,
    mid: str = "mid.1",
    attachments: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    body: dict[str, Any] = {"mid": mid, "seq": 1, "text": text}
    if attachments is not None:
        body["attachments"] = attachments
    return {
        "update_type": "message_created",
        "timestamp": 1_790_000_000_000,
        "message": {
            "sender": user(user_id),
            "recipient": {"chat_id": 555, "chat_type": "dialog", "user_id": 999},
            "timestamp": 1_790_000_000_000,
            "body": body,
        },
    }


def group_message(text: str, *, chat_id: int = -777, mid: str = "mid.g1") -> dict[str, Any]:
    update = dialog_message(text, mid=mid)
    update["message"]["recipient"] = {"chat_id": chat_id, "chat_type": "chat"}
    return update


def callback(payload: str, *, user_id: int = 100, callback_id: str = "cb.1") -> dict[str, Any]:
    return {
        "update_type": "message_callback",
        "timestamp": 1_790_000_000_000,
        "callback": {
            "timestamp": 1_790_000_000_000,
            "callback_id": callback_id,
            "payload": payload,
            "user": user(user_id),
        },
    }


def photo(url: str = "https://i.oneme.ru/i?r=abc") -> dict[str, Any]:
    return {"type": "image", "payload": {"photo_id": 1, "token": "tok", "url": url}}
