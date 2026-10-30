from collections.abc import Awaitable, Callable
from dataclasses import dataclass

import structlog

from yasno.bot.context import BotContext
from yasno.max.types import Update, UpdateType

log = structlog.get_logger(__name__)

type Handler = Callable[[Update, BotContext], Awaitable[None]]
type Predicate = Callable[[Update], bool]


@dataclass(slots=True, frozen=True)
class Route:
    kind: UpdateType
    predicate: Predicate
    handler: Handler


def _always(_: Update) -> bool:
    return True


def callback_prefix(prefix: str) -> Predicate:
    def check(update: Update) -> bool:
        payload = update.callback.payload if update.callback else None
        return payload is not None and payload.split(":", 1)[0] == prefix

    return check


def in_dialog(update: Update) -> bool:
    return update.message is not None and update.message.is_dialog


def in_group(update: Update) -> bool:
    return update.message is not None and not update.message.is_dialog


def has_image(update: Update) -> bool:
    message = update.message
    return message is not None and any(a.type == "image" for a in message.all_attachments())


def has_text(update: Update) -> bool:
    return update.message is not None and bool(update.message.text)


def all_of(*predicates: Predicate) -> Predicate:
    def check(update: Update) -> bool:
        return all(p(update) for p in predicates)

    return check


class Router:
    def __init__(self) -> None:
        self._routes: list[Route] = []

    def on(self, kind: UpdateType, predicate: Predicate = _always) -> Callable[[Handler], Handler]:
        def register(handler: Handler) -> Handler:
            self._routes.append(Route(kind, predicate, handler))
            return handler

        return register

    def include(self, other: "Router") -> None:
        self._routes.extend(other._routes)

    def resolve(self, update: Update) -> Handler | None:
        kind = update.kind
        if kind is None:
            return None
        for route in self._routes:
            if route.kind is kind and route.predicate(update):
                return route.handler
        return None

    async def dispatch(self, update: Update, ctx: BotContext) -> bool:
        handler = self.resolve(update)
        if handler is None:
            log.debug("update_unhandled", update_type=update.update_type)
            return False
        structlog.contextvars.bind_contextvars(
            update_type=update.update_type, user_id=update.actor_id, handler=handler.__qualname__
        )
        try:
            await handler(update, ctx)
        finally:
            structlog.contextvars.unbind_contextvars("update_type", "user_id", "handler")
        return True
