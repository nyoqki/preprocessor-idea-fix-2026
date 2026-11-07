from collections.abc import Iterator
from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from tests import factories
from tests.bot.harness import Harness, make_harness
from tests.bot.test_homework import consented_user
from yasno.db.models import Material

pytestmark = pytest.mark.db

Sessions = async_sessionmaker[AsyncSession]


@pytest.fixture
def harness(db_sessions: Sessions, tmp_path: Path) -> Iterator[Harness]:
    harness = make_harness(db_sessions, tmp_path)
    yield harness
    harness.ctx.verifier.close()


async def test_photo_in_class_chat_becomes_material(
    harness: Harness, db_sessions: Sessions, tmp_path: Path
) -> None:
    await harness.feed(
        {
            "update_type": "bot_added",
            "timestamp": 1,
            "chat_id": -777,
            "user": factories.user(7),
            "is_channel": False,
        }
    )
    from yasno.db.models import SchoolClass, User

    await consented_user(db_sessions)
    async with db_sessions.begin() as session:
        school_class = await session.scalar(select(SchoolClass))
        sender = await session.scalar(select(User).where(User.max_user_id == 100))
        assert school_class is not None
        assert sender is not None
        sender.class_id = school_class.id
    sent_before = len(harness.max.sent)
    harness.chat.push('{"title": "Квадратные уравнения", "topic_codes": ["alg.quadratic_eq"]}')
    update = factories.group_message("", mid="p1")
    update["message"]["body"]["attachments"] = [factories.photo("https://cdn/notes.jpg")]
    await harness.feed(update)

    async with db_sessions() as session:
        material = await session.scalar(select(Material))
    assert material is not None
    assert material.title == "Квадратные уравнения"
    assert material.topic_codes == ["alg.quadratic_eq"]
    assert "2x + 3 = 7" in material.content
    assert material.image_key is not None
    assert await harness.ctx.storage.exists(material.image_key)
    assert harness.max.downloads == ["https://cdn/notes.jpg"]
    assert len(harness.max.sent) == sent_before


async def test_relevant_materials_use_russian_full_text(db_sessions: Sessions) -> None:
    from yasno.db.models import SchoolClass
    from yasno.services.materials import relevant_materials

    async with db_sessions.begin() as session:
        school_class = SchoolClass(title="9А", invite_code="code9a")
        session.add(school_class)
        await session.flush()
        session.add_all(
            [
                Material(
                    class_id=school_class.id,
                    title="Дискриминант",
                    content="Дискриминант квадратного уравнения равен b² − 4ac",
                ),
                Material(
                    class_id=school_class.id,
                    title="Дроби",
                    content="Сложение дробей с разными знаменателями",
                ),
            ]
        )
        class_id = school_class.id
    async with db_sessions() as session:
        found = await relevant_materials(session, class_id, "как найти дискриминант")
    assert len(found) == 1
    assert found[0].startswith("Дискриминант")


async def test_unconnected_sender_is_not_downloaded_or_sent_to_ai(
    harness: Harness, db_sessions: Sessions
) -> None:
    from tests.bot.test_onboarding import bot_added

    await harness.feed(bot_added(chat_id=-777))
    update = factories.group_message("Завтра контрольная по алгебре", mid="unknown")
    update["message"]["body"]["attachments"] = [factories.photo("https://cdn/unknown.jpg")]
    await harness.feed(update)
    assert harness.max.downloads == []
    assert harness.chat.calls == []
    async with db_sessions() as session:
        assert await session.scalar(select(Material)) is None
