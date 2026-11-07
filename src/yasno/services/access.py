import httpx

from yasno.max.client import MaxApiError, MaxClient


async def is_chat_admin(client: MaxClient, chat_id: int | None, user_id: int) -> bool:
    if chat_id is None:
        return False
    try:
        admins = await client.get_admins(chat_id)
    except (MaxApiError, httpx.HTTPError):
        return False
    return any(
        member.user_id == user_id and (member.is_admin or member.is_owner)
        for member in admins.members
    )
