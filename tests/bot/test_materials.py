from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from tests import factories
from tests.bot.harness import Harness, make_harness
from yasno.db.models import Material

pytestmark = pytest.mark.db

Sessions = async_sessionmaker[AsyncSession]


@pytest.fixture
def harness(db_sessions: Sessions, tmp_path: Path) -> Harness:
    return make_harness(db_sessions, tmp_path)


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
