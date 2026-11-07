from datetime import timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from tests.bot.test_homework import consented_user
from yasno.clock import utcnow
from yasno.db.models import Notification, User
from yasno.services import notifications

pytestmark = pytest.mark.db
Sessions = async_sessionmaker[AsyncSession]


@pytest.mark.parametrize(
    ("minutes", "sent", "reclaimed"), [(20, False, True), (1, False, False), (20, True, False)]
)
async def test_claim_recovers_stale_unsent_work_only(
    db_sessions: Sessions, minutes: int, sent: bool, reclaimed: bool
) -> None:
    await consented_user(db_sessions)
    async with db_sessions.begin() as session:
        user = await session.scalar(select(User))
        assert user is not None
        row = Notification(
            user_id=user.id,
            kind="review",
            ref="today",
            created_at=utcnow() - timedelta(minutes=minutes),
            sent_at=utcnow() if sent else None,
        )
        session.add(row)
        await session.flush()
        row_id = row.id
    async with db_sessions.begin() as session:
        claimed = await notifications.claim(session, user.id, "review", "today")
        assert claimed == (row_id if reclaimed else None)
    async with db_sessions.begin() as session:
        assert await notifications.claim(session, user.id, "review", "today") is None
