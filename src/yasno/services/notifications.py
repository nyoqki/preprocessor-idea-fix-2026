from datetime import timedelta

from sqlalchemy import delete, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from yasno.clock import utcnow
from yasno.db.models import Notification


async def claim(session: AsyncSession, user_id: int, kind: str, ref: str) -> int | None:
    now = utcnow()
    result = await session.execute(
        insert(Notification)
        .values(user_id=user_id, kind=kind, ref=ref)
        .on_conflict_do_update(
            index_elements=[Notification.user_id, Notification.kind, Notification.ref],
            set_={"created_at": now},
            where=Notification.sent_at.is_(None)
            & (Notification.created_at < now - timedelta(minutes=15)),
        )
        .returning(Notification.id)
    )
    return result.scalar_one_or_none()


async def mark_sent(session: AsyncSession, notification_id: int) -> None:
    await session.execute(
        update(Notification).where(Notification.id == notification_id).values(sent_at=utcnow())
    )


async def release_failed(session: AsyncSession, notification_id: int) -> None:
    await session.execute(
        delete(Notification).where(
            Notification.id == notification_id, Notification.sent_at.is_(None)
        )
    )
