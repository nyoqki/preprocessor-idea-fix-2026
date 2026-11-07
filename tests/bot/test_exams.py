from collections.abc import Iterator
from datetime import date, timedelta
from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from tests import factories
from tests.bot.harness import Harness, make_harness
from tests.bot.test_homework import consented_user
from yasno.bot.texts import describe_day
from yasno.db.models import Exam, ExamSource

Sessions = async_sessionmaker[AsyncSession]


@pytest.fixture
def harness(db_sessions: Sessions, tmp_path: Path) -> Iterator[Harness]:
    harness = make_harness(db_sessions, tmp_path)
    yield harness
    harness.ctx.verifier.close()


def test_describe_day() -> None:
    today = date(2026, 11, 1)
    assert describe_day(today, today) == "сегодня"
    assert describe_day(today + timedelta(days=1), today) == "завтра"
    assert describe_day(date(2026, 11, 10), today) == "10 ноября"
    assert describe_day(date(2026, 11, 3), today) == "во вторник"
    assert describe_day(date(2026, 11, 5), today) == "в четверг"
    assert describe_day(date(2026, 11, 20), today) == "20 ноября"


@pytest.mark.db
async def test_student_reports_exam_in_dialog(harness: Harness, db_sessions: Sessions) -> None:
    await consented_user(db_sessions)
    harness.chat.push(
        '{"is_exam": true, "subject": "алгебра", "title": "Контрольная работа", '
        '"date": null, "topic_codes": ["alg.quadratic_eq"]}'
    )
    await harness.feed(factories.dialog_message("в пятницу контрольная по алгебре"))
    async with db_sessions() as session:
        exam = await session.scalar(select(Exam))
    assert exam is not None
    assert exam.source is ExamSource.STUDENT
    assert exam.subject == "алгебра"
    assert exam.topic_codes == ["alg.quadratic_eq"]
    assert exam.scheduled_on.weekday() == 4
    assert "по алгебре" in (harness.max.sent[-1].text or "")
    assert harness.max.buttons()[0]["payload"] == f"exam:del:{exam.id}"

    await harness.feed(factories.callback(f"exam:del:{exam.id}", callback_id="d1"))
    async with db_sessions() as session:
        assert await session.scalar(select(Exam)) is None


@pytest.mark.db
async def test_group_announcement_creates_class_exam(
    harness: Harness, db_sessions: Sessions
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
    harness.chat.push(
        '{"is_exam": true, "subject": "геометрия", "title": "Самостоятельная работа", '
        '"date": null, "topic_codes": []}'
    )
    await harness.feed(factories.group_message("Завтра самостоятельная по геометрии", mid="g1"))
    await harness.feed(factories.group_message("кто идёт в столовую?", mid="g2"))
    async with db_sessions() as session:
        exams = list((await session.execute(select(Exam))).scalars())
    assert len(exams) == 1
    assert exams[0].source is ExamSource.CHAT
    assert exams[0].class_id is not None
    assert len(harness.max.sent) == sent_before


@pytest.mark.db
async def test_free_text_question_is_answered_with_daily_limit(
    harness: Harness, db_sessions: Sessions
) -> None:
    await consented_user(db_sessions)
    harness.chat.push("Дискриминант показывает, сколько корней у квадратного уравнения.")
    await harness.feed(factories.dialog_message("что такое дискриминант?", mid="q1"))
    assert "Дискриминант" in (harness.max.sent[-1].text or "")


@pytest.mark.db
@pytest.mark.parametrize("text", ["что такое дискриминант?", "завтра контрольная по алгебре"])
async def test_text_without_consent_does_not_reach_ai(
    harness: Harness, db_sessions: Sessions, text: str
) -> None:
    await harness.feed(factories.dialog_message(text))
    assert harness.chat.calls == []
    assert "согласие" in harness.max.texts_to(100)[0]
    async with db_sessions() as session:
        assert await session.scalar(select(Exam)) is None


@pytest.mark.db
async def test_personal_exam_stays_private_for_class_member(
    harness: Harness, db_sessions: Sessions
) -> None:
    from yasno.db.models import SchoolClass, User

    await consented_user(db_sessions)
    async with db_sessions.begin() as session:
        school_class = SchoolClass(title="9Б", invite_code="private-exam")
        session.add(school_class)
        await session.flush()
        student = await session.scalar(select(User).where(User.max_user_id == 100))
        assert student is not None
        student.class_id = school_class.id
    await harness.feed(factories.dialog_message("завтра контрольная по алгебре"))
    async with db_sessions() as session:
        exam = await session.scalar(select(Exam))
    assert exam is not None
    assert exam.user_id == student.id
    assert exam.class_id is None
