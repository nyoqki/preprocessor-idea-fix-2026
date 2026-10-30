from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from tests.bot.harness import Harness, make_harness
from yasno.db.models import ConsentStatus, Exam, ExamSource, Role, SchoolClass, User
from yasno.math.errors import ErrorType
from yasno.services.progress import record_mistake
from yasno.worker import reminders

pytestmark = pytest.mark.db

Sessions = async_sessionmaker[AsyncSession]
NOW = datetime(2026, 11, 2, 9, 30, tzinfo=UTC)


@pytest.fixture
def harness(
    db_sessions: Sessions, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> Iterator[Harness]:
    monkeypatch.setattr(reminders, "local_now", lambda tz: NOW)
    monkeypatch.setattr(reminders, "utcnow", lambda: NOW)
    harness = make_harness(db_sessions, tmp_path)
    yield harness
    harness.ctx.verifier.close()


async def seed_class(sessions: Sessions) -> tuple[int, list[User]]:
    async with sessions.begin() as session:
        school_class = SchoolClass(title="9Б", grade=9, invite_code="abc")
        session.add(school_class)
        await session.flush()
        users = [
            User(
                max_user_id=1000 + i,
                first_name=f"u{i}",
                class_id=school_class.id,
                consent_status=ConsentStatus.GRANTED if i < 3 else ConsentStatus.NONE,
            )
            for i in range(4)
        ]
        users.append(
            User(max_user_id=2000, first_name="t", class_id=school_class.id, role=Role.TEACHER)
        )
        session.add_all(users)
        await session.flush()
        return school_class.id, users


async def test_exam_reminder_reaches_consented_students_once(
    harness: Harness, db_sessions: Sessions
) -> None:
    class_id, _ = await seed_class(db_sessions)
    async with db_sessions.begin() as session:
        session.add(
            Exam(
                class_id=class_id,
                subject="алгебра",
                title="Контрольная работа",
                topic_codes=["alg.quadratic_eq"],
                scheduled_on=NOW.date() + timedelta(days=2),
                source=ExamSource.CHAT,
            )
        )
    job = {"bot": harness.ctx}
    assert await reminders.send_exam_reminders(job) == 3
    assert await reminders.send_exam_reminders(job) == 0
    text = harness.max.sent[0].text or ""
    assert text.startswith("Послезавтра контрольная работа по алгебре (Квадратные уравнения)")
    assert harness.max.buttons(0)[0]["payload"].startswith("quiz:exam:")
    assert {s.user_id for s in harness.max.sent} == {1000, 1001, 1002}


async def test_exam_reminders_respect_quiet_hours(
    harness: Harness, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(reminders, "local_now", lambda tz: NOW.replace(hour=23))
    assert await reminders.send_exam_reminders({"bot": harness.ctx}) == 0


async def test_review_reminder_once_per_day(harness: Harness, db_sessions: Sessions) -> None:
    _, users = await seed_class(db_sessions)
    async with db_sessions.begin() as session:
        for topic in ("alg.quadratic_eq", "arith.fractions"):
            await record_mistake(
                session,
                user_id=users[0].id,
                topic_code=topic,
                error_type=ErrorType.SIGN,
                now=NOW - timedelta(days=3),
            )
    job = {"bot": harness.ctx}
    assert await reminders.send_review_reminders(job) == 1
    assert await reminders.send_review_reminders(job) == 0
    assert harness.max.sent[0].user_id == users[0].max_user_id


async def test_teacher_digest_is_anonymous_and_thresholded(
    harness: Harness, db_sessions: Sessions
) -> None:
    _, users = await seed_class(db_sessions)
    async with db_sessions.begin() as session:
        for user in users[:2]:
            await record_mistake(
                session,
                user_id=user.id,
                topic_code="alg.quadratic_eq",
                error_type=ErrorType.FORMULA,
                now=NOW,
            )
        await record_mistake(
            session,
            user_id=users[2].id,
            topic_code="arith.powers",
            error_type=ErrorType.POWERS,
            now=NOW,
        )
    assert await reminders.send_teacher_digest({"bot": harness.ctx}) == 1
    message = harness.max.sent[0]
    assert message.user_id == 2000
    assert "Квадратные уравнения — 2 из 4" in (message.text or "")
    assert "Степени" not in (message.text or "")
    assert all(u.first_name not in (message.text or "") for u in users[:3])
