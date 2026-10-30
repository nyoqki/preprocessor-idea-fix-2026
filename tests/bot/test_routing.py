from typing import Any, cast

from tests import factories
from yasno.bot.context import BotContext
from yasno.bot.routing import Router, all_of, callback_prefix, has_image, in_dialog
from yasno.max.types import Update, UpdateType


async def test_routes_by_kind_and_predicate_in_registration_order() -> None:
    router = Router()
    calls: list[str] = []

    @router.on(UpdateType.MESSAGE_CREATED, all_of(in_dialog, has_image))
    async def photo(update: Update, ctx: BotContext) -> None:
        calls.append("photo")

    @router.on(UpdateType.MESSAGE_CREATED, in_dialog)
    async def text(update: Update, ctx: BotContext) -> None:
        calls.append("text")

    @router.on(UpdateType.MESSAGE_CALLBACK, callback_prefix("quiz"))
    async def quiz(update: Update, ctx: BotContext) -> None:
        calls.append("quiz")

    ctx = cast(BotContext, object())
    with_photo = factories.dialog_message(None, attachments=[factories.photo()])
    raws: list[dict[str, Any]] = [
        with_photo,
        factories.dialog_message("hi"),
        factories.callback("quiz:5:1"),
        factories.callback("other:1"),
        factories.group_message("hi"),
    ]
    handled = [await router.dispatch(Update.model_validate(raw), ctx) for raw in raws]
    assert calls == ["photo", "text", "quiz"]
    assert handled == [True, True, True, False, False]
