from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from yasno.db.models import User
from yasno.max import types as max_types


async def upsert_user(session: AsyncSession, actor: max_types.User) -> User:
    now = datetime.now(UTC)
    stmt = (
        insert(User)
        .values(
            max_user_id=actor.user_id,
            first_name=actor.first_name,
            last_name=actor.last_name,
            username=actor.username,
            last_seen_at=now,
        )
        .on_conflict_do_update(
            index_elements=[User.max_user_id],
            set_={
                "first_name": actor.first_name,
                "last_name": actor.last_name,
                "username": actor.username,
                "last_seen_at": now,
                "dialog_available": True,
            },
        )
        .returning(User)
    )
    result = await session.execute(stmt.execution_options(populate_existing=True))
    return result.scalar_one()


async def get_by_max_id(session: AsyncSession, max_user_id: int) -> User | None:
    result = await session.execute(select(User).where(User.max_user_id == max_user_id))
    return result.scalar_one_or_none()


async def mark_dialog_unavailable(session: AsyncSession, max_user_id: int) -> None:
    user = await get_by_max_id(session, max_user_id)
    if user is not None:
        user.dialog_available = False
