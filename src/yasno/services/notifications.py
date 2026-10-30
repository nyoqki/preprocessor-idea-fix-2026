from sqlalchemy import update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from yasno.clock import utcnow
from yasno.db.models import Notification


async def claim(session: AsyncSession, user_id: int, kind: str, ref: str) -> int | None:
    result = await session.execute(
        insert(Notification)
        .values(user_id=user_id, kind=kind, ref=ref)
        .on_conflict_do_nothing(
            index_elements=[Notification.user_id, Notification.kind, Notification.ref]
        )
        .returning(Notification.id)
    )
    return result.scalar_one_or_none()


async def mark_sent(session: AsyncSession, notification_id: int) -> None:
    await session.execute(
        update(Notification).where(Notification.id == notification_id).values(sent_at=utcnow())
    )
