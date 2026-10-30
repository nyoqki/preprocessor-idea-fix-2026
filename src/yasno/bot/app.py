from yasno.bot.handlers import dialog, group, homework, start
from yasno.bot.routing import Router


def build_router() -> Router:
    router = Router()
    router.include(start.router)
    router.include(group.router)
    router.include(homework.router)
    router.include(dialog.router)
    return router
