import asyncio
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from tests import factories
from tests.bot.harness import make_harness
from tests.bot.test_homework import consented_user
from yasno.db.models import Submission, SubmissionKind, SubmissionStatus, User
from yasno.worker import app

pytestmark = pytest.mark.db
Sessions = async_sessionmaker[AsyncSession]


@pytest.mark.parametrize("times_out", [False, True])
async def test_failed_update_finishes_pending_work_without_overwriting_done(
    db_sessions: Sessions, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, times_out: bool
) -> None:
    harness = make_harness(db_sessions, tmp_path)
    await consented_user(db_sessions)
    raw = factories.dialog_message()
    mid = raw["message"]["body"]["mid"]
    async with db_sessions.begin() as session:
        user = await session.scalar(select(User))
        assert user is not None
        session.add_all(
            [
                Submission(
                    user_id=user.id,
                    kind=SubmissionKind.HOMEWORK,
                    source_mid=mid,
                    status=SubmissionStatus.PROCESSING,
                ),
                Submission(
                    user_id=user.id,
                    kind=SubmissionKind.HOMEWORK,
                    source_mid=mid,
                    status=SubmissionStatus.DONE,
                ),
            ]
        )

    class BrokenRouter:
        async def dispatch(self, *_: Any) -> None:
            if times_out:
                await asyncio.sleep(10)
            raise RuntimeError("synthetic processing failure")

    monkeypatch.setattr(app, "UPDATE_TIMEOUT_SECONDS", 0.01 if times_out else 240)
    try:
        await app.handle_update({"bot": harness.ctx, "router": BrokenRouter()}, raw)
        async with db_sessions() as session:
            statuses = list(await session.scalars(select(Submission.status)))
        assert sorted(statuses) == [SubmissionStatus.DONE, SubmissionStatus.FAILED]
        assert "Что-то пошло не так" in harness.max.texts_to(100)[-1]
    finally:
        harness.ctx.verifier.close()
