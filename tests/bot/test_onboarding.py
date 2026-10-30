from collections.abc import Iterator
from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from tests import factories
from tests.bot.harness import Harness, make_harness
from yasno.db.models import ConsentStatus, Role, SchoolClass, User
from yasno.services.consent import parent_token

pytestmark = pytest.mark.db

Sessions = async_sessionmaker[AsyncSession]


@pytest.fixture
def harness(db_sessions: Sessions, tmp_path: Path) -> Iterator[Harness]:
    harness = make_harness(db_sessions, tmp_path)
    yield harness
    harness.ctx.verifier.close()


def bot_started(user_id: int = 100, payload: str | None = None) -> dict[str, object]:
    return {
        "update_type": "bot_started",
        "timestamp": 1,
        "chat_id": 555,
        "user": factories.user(user_id),
        "payload": payload,
    }


def bot_added(chat_id: int = -900) -> dict[str, object]:
    return {
        "update_type": "bot_added",
        "timestamp": 1,
        "chat_id": chat_id,
        "user": factories.user(7),
        "is_channel": False,
    }


async def user_by_max_id(sessions: Sessions, max_user_id: int) -> User:
    async with sessions() as session:
        user = await session.scalar(select(User).where(User.max_user_id == max_user_id))
    assert user is not None
    return user


async def test_start_asks_grade_then_consent(harness: Harness, db_sessions: Sessions) -> None:
    await harness.feed(bot_started())
    assert "Ясно" in harness.max.texts_to(100)[0]
    assert [b["payload"] for b in harness.max.buttons()] == [
        "grade:8",
        "grade:9",
        "grade:10",
        "grade:11",
    ]
    await harness.feed(factories.callback("grade:9", callback_id="c1"))
    user = await user_by_max_id(db_sessions, 100)
    assert user.grade == 9
    assert harness.max.buttons()[0]["payload"] == "consent:adult"
    await harness.feed(factories.callback("consent:adult", callback_id="c2"))
    user = await user_by_max_id(db_sessions, 100)
    assert user.consent_status is ConsentStatus.GRANTED


async def test_class_connection_and_join(harness: Harness, db_sessions: Sessions) -> None:
    await harness.feed(bot_added())
    group_message = harness.max.sent[-1]
    assert group_message.chat_id == -900
    links = [b["url"] for b in harness.max.buttons()]
    assert links[0].startswith("https://max.ru/yasno_bot?start=join_")
    async with db_sessions() as session:
        school_class = await session.scalar(select(SchoolClass))
    assert school_class is not None
    assert school_class.grade == 9
    assert school_class.bot_can_read_chat

    await harness.feed(bot_started(101, f"join_{school_class.invite_code}"))
    student = await user_by_max_id(db_sessions, 101)
    assert student.class_id == school_class.id
    assert student.grade == 9
    assert student.role is Role.STUDENT

    await harness.feed(bot_started(102, f"teach_{school_class.invite_code}"))
    teacher = await user_by_max_id(db_sessions, 102)
    assert teacher.role is Role.TEACHER


async def test_invalid_invite_is_reported(harness: Harness) -> None:
    await harness.feed(bot_started(103, "teach_nope"))
    assert any("устарела" in t for t in harness.max.texts_to(103))


async def test_parent_consent_flow(harness: Harness, db_sessions: Sessions) -> None:
    await harness.feed(bot_started(104))
    child = await user_by_max_id(db_sessions, 104)
    await harness.feed(factories.callback("consent:minor", user_id=104, callback_id="c3"))
    assert "parent_" in harness.max.callbacks[-1]["text"]

    token = parent_token("bot-token", child.id)
    await harness.feed(bot_started(200, f"parent_{token}"))
    assert harness.max.buttons()[0]["payload"] == f"parent:{token}"
    await harness.feed(factories.callback(f"parent:{token}", user_id=200, callback_id="c4"))
    child = await user_by_max_id(db_sessions, 104)
    assert child.consent_status is ConsentStatus.GRANTED
    assert any("подтвердил" in t for t in harness.max.texts_to(104))


async def test_forged_parent_token_is_rejected(harness: Harness, db_sessions: Sessions) -> None:
    await harness.feed(bot_started(105))
    child = await user_by_max_id(db_sessions, 105)
    await harness.feed(
        factories.callback(f"parent:{child.id}_9999999999_forged", user_id=201, callback_id="c5")
    )
    child = await user_by_max_id(db_sessions, 105)
    assert child.consent_status is ConsentStatus.NONE
