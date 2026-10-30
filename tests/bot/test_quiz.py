from collections.abc import Iterator
from datetime import date, timedelta
from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from tests import factories
from tests.bot.harness import Harness, make_harness
from yasno.db.models import (
    ConsentStatus,
    Exam,
    ExamSource,
    Mistake,
    Quiz,
    QuizStatus,
    SchoolClass,
    TopicProgress,
    User,
)
from yasno.math.generators import supported_topics
from yasno.services.quizzes import plan_topics

Sessions = async_sessionmaker[AsyncSession]


@pytest.fixture
def harness(db_sessions: Sessions, tmp_path: Path) -> Iterator[Harness]:
    harness = make_harness(db_sessions, tmp_path)
    yield harness
    harness.ctx.verifier.close()


def test_plan_mixes_exam_topics_with_personal_gaps() -> None:
    plan = plan_topics(["alg.quadratic_eq", "geom.planimetry"], ["arith.fractions"], 9, 5)
    assert len(plan) == 5
    assert set(plan) == {"alg.quadratic_eq", "arith.fractions"}
    assert all(topic in supported_topics() for topic in plan)


def test_plan_falls_back_to_grade_defaults() -> None:
    plan = plan_topics([], [], 11, 3)
    assert plan
    assert all(topic in supported_topics() for topic in plan)


async def seed(sessions: Sessions) -> tuple[int, int]:
    async with sessions.begin() as session:
        school_class = SchoolClass(title="9Б", grade=9, invite_code="q9b")
        session.add(school_class)
        await session.flush()
        user = User(
            max_user_id=100,
            first_name="Аня",
            grade=9,
            class_id=school_class.id,
            consent_status=ConsentStatus.GRANTED,
        )
        exam = Exam(
            class_id=school_class.id,
            subject="алгебра",
            title="Контрольная работа",
            topic_codes=["alg.quadratic_eq"],
            scheduled_on=date.today() + timedelta(days=2),
            source=ExamSource.CHAT,
        )
        session.add_all([user, exam])
        await session.flush()
        return user.id, exam.id


@pytest.mark.db
async def test_exam_quiz_runs_in_chat_and_updates_progress(
    harness: Harness, db_sessions: Sessions
) -> None:
    user_id, exam_id = await seed(db_sessions)
    await harness.feed(factories.callback(f"quiz:exam:{exam_id}", callback_id="s"))
    assert "5 вопросов" in harness.max.callbacks[-1]["text"]

    answers = 0
    while True:
        message = harness.max.sent[-1]
        if not (message.text or "").startswith("Вопрос"):
            break
        buttons = harness.max.buttons()
        assert len(buttons) == 4
        wrong = answers == 0
        async with db_sessions() as session:
            quiz = await session.scalar(select(Quiz).where(Quiz.status == QuizStatus.ACTIVE))
            assert quiz is not None
        payloads = [b["payload"] for b in buttons]
        chosen = payloads[0]
        if wrong:
            async with db_sessions() as session:
                from yasno.db.models import QuizItem

                item_id = int(chosen.split(":")[3])
                item = await session.get(QuizItem, item_id)
                assert item is not None
                chosen = payloads[(item.correct_index + 1) % 4]
        await harness.feed(factories.callback(chosen, callback_id=f"a{answers}"))
        answers += 1
        assert answers <= 5

    assert answers == 5
    assert harness.max.sent[-1].text is not None
    assert harness.max.sent[-1].text.startswith("Готово:")
    assert "Не совсем" in harness.max.callbacks[1]["text"]
    async with db_sessions() as session:
        quiz = await session.scalar(select(Quiz))
        mistakes = list((await session.execute(select(Mistake))).scalars())
        progress = list((await session.execute(select(TopicProgress))).scalars())
    assert quiz is not None
    assert quiz.status is QuizStatus.COMPLETED
    assert quiz.exam_id == exam_id
    assert len(mistakes) >= 1
    assert mistakes[0].quiz_item_id is not None
    assert progress
    assert all(p.user_id == user_id for p in progress)


@pytest.mark.db
async def test_repeated_answer_is_ignored(harness: Harness, db_sessions: Sessions) -> None:
    await seed(db_sessions)
    await harness.feed(factories.callback("quiz:topic:alg.linear_eq", callback_id="s"))
    payload = harness.max.buttons()[0]["payload"]
    await harness.feed(factories.callback(payload, callback_id="a1"))
    await harness.feed(factories.callback(payload, callback_id="a2"))
    assert harness.max.callbacks[-1]["notification"] == "Ты уже ответил на этот вопрос."


@pytest.mark.db
async def test_quiz_requires_consent(harness: Harness) -> None:
    await harness.feed(factories.callback("quiz:topic:alg.linear_eq", callback_id="s"))
    assert "согласие" in harness.max.callbacks[-1]["notification"]


@pytest.mark.db
async def test_unknown_topic_is_unavailable(harness: Harness, db_sessions: Sessions) -> None:
    await seed(db_sessions)
    await harness.feed(factories.callback("quiz:topic:geom.planimetry", callback_id="s"))
    assert harness.max.callbacks[-1]["text"] == "Этот тест уже недоступен."
