from tests import factories
from yasno.max.types import ChatType, Update, UpdateType


def test_parses_dialog_message() -> None:
    update = Update.model_validate(factories.dialog_message("  x = 2  "))
    assert update.kind is UpdateType.MESSAGE_CREATED
    assert update.message is not None
    assert update.message.is_dialog
    assert update.message.text == "x = 2"
    assert update.actor_id == 100


def test_unknown_update_type_is_tolerated() -> None:
    update = Update.model_validate({"update_type": "something_new", "timestamp": 1})
    assert update.kind is None


def test_photo_attachment_exposes_url() -> None:
    raw = factories.dialog_message(None, attachments=[factories.photo("https://cdn/x.jpg")])
    update = Update.model_validate(raw)
    assert update.message is not None
    images = update.message.body.attachments_of("image")
    assert [a.url for a in images] == ["https://cdn/x.jpg"]


def test_forwarded_attachments_are_included() -> None:
    raw = factories.dialog_message(None)
    raw["message"]["link"] = {
        "type": "forward",
        "message": {"mid": "m2", "seq": 1, "attachments": [factories.photo()]},
    }
    update = Update.model_validate(raw)
    assert update.message is not None
    assert [a.type for a in update.message.all_attachments()] == ["image"]


def test_group_message_is_not_dialog() -> None:
    update = Update.model_validate(factories.group_message("контрольная в четверг"))
    assert update.message is not None
    assert update.message.recipient.chat_type is ChatType.CHAT
    assert not update.message.is_dialog


def test_dedup_key_is_stable_per_message_and_callback() -> None:
    a = Update.model_validate(factories.dialog_message(mid="m1"))
    b = Update.model_validate(factories.dialog_message(mid="m1"))
    c = Update.model_validate(factories.callback("quiz:1", callback_id="c9"))
    assert a.dedup_key() == b.dedup_key()
    assert c.dedup_key() == "cb:c9"
