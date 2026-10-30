from urllib.parse import quote


def start_link(bot_username: str, payload: str) -> str:
    return f"https://max.ru/{bot_username}?start={quote(payload, safe='_-')}"


def app_link(bot_username: str, payload: str | None = None) -> str:
    base = f"https://max.ru/{bot_username}?startapp"
    return f"{base}={quote(payload, safe='_-')}" if payload else base
