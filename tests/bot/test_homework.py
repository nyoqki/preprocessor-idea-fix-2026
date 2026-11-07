from collections.abc import Iterator
from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from tests import factories
from tests.bot.harness import Harness, make_harness
from yasno.ai.fakes import FakeVision
from yasno.ai.types import TranscribedLine, Transcription
from yasno.db.models import (
    ConsentStatus,
    Mistake,
    Submission,
    SubmissionStatus,
    TopicProgress,
    User,
)

pytestmark = pytest.mark.db

Sessions = async_sessionmaker[AsyncSession]


@pytest.fixture
def harness(db_sessions: Sessions, tmp_path: Path) -> Iterator[Harness]:
    harness = make_harness(db_sessions, tmp_path)
    yield harness
    harness.ctx.verifier.close()


async def consented_user(sessions: Sessions, max_user_id: int = 100) -> None:
    async with sessions.begin() as session:
        session.add(
            User(
                max_user_id=max_user_id,
                first_name="Аня",
                grade=9,
                consent_status=ConsentStatus.GRANTED,
            )
        )


def photo_message(mid: str = "ph1") -> dict[str, object]:
    return factories.dialog_message(None, mid=mid, attachments=[factories.photo()])


def use_transcription(harness: Harness, *lines: tuple[str, float]) -> None:
    vision = harness.ctx.tutor.vision
    assert isinstance(vision, FakeVision)
    vision.result = Transcription(
        task="Реши уравнение",
        lines=[
            TranscribedLine(index=i + 1, latex=latex, confidence=confidence)
            for i, (latex, confidence) in enumerate(lines)
        ],
    )


async def test_sign_error_is_found_explained_and_recorded(
    harness: Harness, db_sessions: Sessions
) -> None:
    await consented_user(db_sessions)
    await harness.feed(photo_message())
    texts = harness.max.texts_to(100)
    assert texts[0] == "Смотрю решение…"
    assert texts[-1].startswith("Строка 2: 2x = 7 + 3")
    assert "x = 5" not in texts[-1]
    assert harness.max.buttons()[0]["type"] == "open_app"
    assert harness.max.buttons()[0]["payload"].startswith("submission_")
    async with db_sessions() as session:
        submission = await session.scalar(select(Submission))
        mistake = await session.scalar(select(Mistake))
        progress = await session.scalar(select(TopicProgress))
    assert submission is not None
    assert submission.status is SubmissionStatus.DONE
    assert submission.analysis is not None
    assert submission.analysis["first_error_step"] == 2
    assert submission.analysis["error_type"] == "sign"
    assert mistake is not None
    assert mistake.error_type == "sign"
    assert mistake.topic_code == "alg.linear_eq"
    assert progress is not None
    assert progress.mistakes_total == 1


async def test_correct_solution_offers_practice(harness: Harness, db_sessions: Sessions) -> None:
    await consented_user(db_sessions)
    use_transcription(harness, ("2x + 3 = 7", 0.99), ("2x = 4", 0.99), ("x = 2", 0.99))
    await harness.feed(photo_message())
    assert harness.max.texts_to(100)[-1].startswith("Всё верно!")
    assert harness.max.buttons()[0]["payload"] == "quiz:topic:alg.linear_eq"
    async with db_sessions() as session:
        progress = await session.scalar(select(TopicProgress))
    assert progress is not None
    assert progress.correct_total == 1


async def test_doubtful_line_is_confirmed_then_fixed(
    harness: Harness, db_sessions: Sessions
) -> None:
    await consented_user(db_sessions)
    use_transcription(harness, ("2x + 3 = 7", 0.99), ("2x = 4", 0.3), ("x = 2", 0.99))
    await harness.feed(photo_message())
    assert "2? 2x = 4" in harness.max.texts_to(100)[-1]
    fix = harness.max.buttons()[1]["payload"]
    assert fix.startswith("sub:fix:")
    await harness.feed(factories.callback(fix, callback_id="f1"))
    await harness.feed(factories.dialog_message("2: 2x = 10", mid="t1"))
    assert harness.max.texts_to(100)[-1].startswith("Строка 2: 2x = 10")


async def test_same_photo_is_not_analyzed_twice(harness: Harness, db_sessions: Sessions) -> None:
    await consented_user(db_sessions)
    await harness.feed(photo_message("a"))
    await harness.feed(photo_message("b"))
    assert harness.max.texts_to(100)[-1].startswith("Эту работу я уже разбирал")
    async with db_sessions() as session:
        count = len(list((await session.execute(select(Submission))).scalars()))
    assert count == 1


async def test_photo_without_consent_is_not_stored(
    harness: Harness, db_sessions: Sessions, tmp_path: Path
) -> None:
    await harness.feed(photo_message())
    assert "согласие" in harness.max.texts_to(100)[0]
    assert harness.max.downloads == []
    async with db_sessions() as session:
        assert await session.scalar(select(Submission)) is None


async def test_followup_text_continues_the_dialog(harness: Harness, db_sessions: Sessions) -> None:
    await consented_user(db_sessions)
    await harness.feed(photo_message())
    harness.chat.push("Верно, при переносе знак меняется. А что тогда будет во второй строке?")
    await harness.feed(factories.dialog_message("знак меняется?", mid="q1"))
    assert harness.max.texts_to(100)[-1].startswith("Верно, при переносе")
    last_call = harness.chat.calls[-1]
    assert any("2x = 7 + 3" in m.content for m in last_call)


async def test_followup_remembers_previous_turns(harness: Harness, db_sessions: Sessions) -> None:
    await consented_user(db_sessions)
    await harness.feed(photo_message())
    harness.chat.push("Какой знак станет у 3 после переноса?", "Верно! Что дальше?")
    await harness.feed(factories.dialog_message("не понимаю", mid="q1"))
    await harness.feed(factories.dialog_message("плюс", mid="q2"))
    contents = [m.content for m in harness.chat.calls[-1]]
    assert any(c.startswith("Строка 2:") for c in contents)
    assert "не понимаю" in contents
    assert "Какой знак станет у 3 после переноса?" in contents
    assert contents[-1] == "плюс"


async def test_new_photo_starts_a_fresh_dialog(harness: Harness, db_sessions: Sessions) -> None:
    await consented_user(db_sessions)
    await harness.feed(photo_message())
    await harness.feed(factories.dialog_message("не понимаю", mid="q1"))
    harness.max.image = harness.max.image + b"\x00"
    await harness.feed(photo_message("ph2"))
    await harness.feed(factories.dialog_message("а теперь?", mid="q2"))
    assert "не понимаю" not in [m.content for m in harness.chat.calls[-1]]


async def test_photo_without_math_gets_its_own_reply(
    harness: Harness, db_sessions: Sessions
) -> None:
    await consented_user(db_sessions)
    vision = harness.ctx.tutor.vision
    assert isinstance(vision, FakeVision)
    vision.result = Transcription(is_math=False)
    await harness.feed(photo_message())
    assert harness.max.texts_to(100)[-1].startswith("На фото не вижу решения")


async def test_invalid_line_number_keeps_correction_pending(
    harness: Harness, db_sessions: Sessions
) -> None:
    await consented_user(db_sessions)
    use_transcription(harness, ("2x + 3 = 7", 0.99), ("2x = 4", 0.3), ("x = 2", 0.99))
    await harness.feed(photo_message())
    fix = harness.max.buttons()[1]["payload"]
    await harness.feed(factories.callback(fix))
    await harness.feed(factories.dialog_message("99: x = 2", mid="bad"))
    assert "Такой строки" in harness.max.texts_to(100)[-1]
    await harness.feed(factories.dialog_message("2: 2x = 4", mid="good"))
    assert harness.max.texts_to(100)[-1].startswith("Всё верно!")


async def test_old_confirmation_does_not_count_result_twice(
    harness: Harness, db_sessions: Sessions
) -> None:
    await consented_user(db_sessions)
    use_transcription(harness, ("2x + 3 = 7", 0.99), ("2x = 4", 0.3), ("x = 2", 0.99))
    await harness.feed(photo_message())
    confirm = harness.max.buttons()[0]["payload"]
    await harness.feed(factories.callback(confirm, callback_id="once"))
    await harness.feed(factories.callback(confirm, callback_id="twice"))
    async with db_sessions() as session:
        progress = await session.scalar(select(TopicProgress))
    assert progress is not None
    assert progress.correct_total == 1


async def test_followup_cannot_reveal_final_answer(harness: Harness, db_sessions: Sessions) -> None:
    await consented_user(db_sessions)
    await harness.feed(photo_message())
    harness.chat.push("Ответ: x = 2.")
    await harness.feed(factories.dialog_message("скажи готовый ответ", mid="leak"))
    assert "x = 2" not in harness.max.texts_to(100)[-1]
    assert "Какое правило" in harness.max.texts_to(100)[-1]


async def test_followup_obeys_daily_question_limit(harness: Harness, db_sessions: Sessions) -> None:
    from yasno.clock import local_today

    await consented_user(db_sessions)
    await harness.feed(photo_message())
    async with db_sessions() as session:
        user = await session.scalar(select(User))
    assert user is not None
    day = local_today(harness.ctx.settings.timezone)
    await harness.ctx.redis.set(f"questions:{user.id}:{day.isoformat()}", "30")
    calls = len(harness.chat.calls)
    await harness.feed(factories.dialog_message("а теперь скажи ответ", mid="limit"))
    assert len(harness.chat.calls) == calls
    assert "завтра" in harness.max.texts_to(100)[-1]


async def test_long_ocr_confirmation_preserves_text_and_buttons(harness: Harness) -> None:
    from yasno.bot.common import reply
    from yasno.max import keyboard

    text = "\n".join(f"{index}. " + "а" * 390 for index in range(1, 31))
    rows = [[keyboard.callback("Подтвердить", "sub:ok:1")]]
    await reply(harness.ctx, 100, text, rows)
    assert "".join(harness.max.texts_to(100)) == text
    assert all(len(message) <= 4000 for message in harness.max.texts_to(100))
    assert all(sent.attachments is None for sent in harness.max.sent[:-1])
    assert harness.max.buttons()[0]["payload"] == "sub:ok:1"


async def test_unknown_topic_does_not_become_a_linear_equation_gap(
    harness: Harness, db_sessions: Sessions
) -> None:
    from yasno.ai.types import ProviderError

    await consented_user(db_sessions)
    harness.chat.push(ProviderError("chat", "unavailable"))
    await harness.feed(photo_message())
    async with db_sessions() as session:
        submission = await session.scalar(select(Submission))
        assert submission is not None
        assert submission.status is SubmissionStatus.DONE
        assert submission.topic_code is None
        assert await session.scalar(select(TopicProgress)) is None
