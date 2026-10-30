from yasno.bot.handlers import start
from yasno.bot.routing import Router


def build_router() -> Router:
    router = Router()
    router.include(start.router)
    return router
