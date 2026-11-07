import asyncio
from collections.abc import Iterator, Sequence
from pathlib import Path

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from tests.bot.harness import Harness, make_harness
from tests.bot.test_homework import consented_user
from yasno.bot import memory
from yasno.bot.handlers.homework import deps
from yasno.clock import utcnow
from yasno.db.models import Mistake, Quiz, QuizReason, QuizStatus, Submission, TopicProgress, User
from yasno.math.verification import Verification
from yasno.services import consent, quizzes
from yasno.services.analysis import Verdict, evaluate, start_submission, transcribe

pytestmark = pytest.mark.db
Sessions = async_sessionmaker[AsyncSession]


@pytest.fixture
def harness(db_sessions: Sessions, tmp_path: Path) -> Iterator[Harness]:
    harness = make_harness(db_sessions, tmp_path)
    yield harness
    harness.ctx.verifier.close()


async def pending(harness: Harness, sessions: Sessions) -> tuple[User, Submission]:
    await consented_user(sessions)
    async with sessions() as session:
        user = await session.scalar(select(User))
    assert user is not None
    submission, mime = await start_submission(
        deps(harness.ctx), user_id=user.id, image=harness.max.image, source_mid="concurrent"
    )
    assert submission is not None
    await transcribe(deps(harness.ctx), submission.id, harness.max.image, mime)
    return user, submission


async def test_parallel_evaluation_records_one_mistake(
    harness: Harness, db_sessions: Sessions, monkeypatch: pytest.MonkeyPatch
) -> None:
    user, submission = await pending(harness, db_sessions)
    original = harness.ctx.verifier.verify
    arrived = 0
    ready = asyncio.Event()

    async def synchronize(lines: Sequence[str], task: str | None) -> Verification:
        nonlocal arrived
        result = await original(lines, task)
        arrived += 1
        if arrived == 2:
            ready.set()
        await asyncio.wait_for(ready.wait(), 10)
        return result

    monkeypatch.setattr(harness.ctx.verifier, "verify", synchronize)
    results = await asyncio.gather(
        *(
            evaluate(deps(harness.ctx), submission_id=submission.id, user_id=user.id, grade=9)
            for _ in range(2)
        )
    )
    assert sorted(result.verdict for result in results) == [Verdict.CANCELLED, Verdict.ERROR]
    async with db_sessions() as session:
        assert await session.scalar(select(func.count()).select_from(Mistake)) == 1
        progress = await session.scalar(select(TopicProgress))
    assert progress is not None
    assert progress.mistakes_total == 1


async def test_erasure_during_evaluation_does_not_restore_data(
    harness: Harness, db_sessions: Sessions, monkeypatch: pytest.MonkeyPatch
) -> None:
    user, submission = await pending(harness, db_sessions)
    original = harness.ctx.verifier.verify
    entered, released = asyncio.Event(), asyncio.Event()

    async def suspend(lines: Sequence[str], task: str | None) -> Verification:
        entered.set()
        await asyncio.wait_for(released.wait(), 10)
        return await original(lines, task)

    monkeypatch.setattr(harness.ctx.verifier, "verify", suspend)
    running = asyncio.create_task(
        evaluate(deps(harness.ctx), submission_id=submission.id, user_id=user.id, grade=9)
    )
    try:
        await asyncio.wait_for(entered.wait(), 10)
        async with db_sessions.begin() as session:
            fresh = await session.get(User, user.id)
            assert fresh is not None
            await consent.erase_user_data(session, harness.ctx.storage, fresh)
    finally:
        released.set()
    assert (await running).verdict is Verdict.CANCELLED
    await memory.remember_exchange(harness.ctx, user, "stale question", "stale answer")
    assert await memory.load(harness.ctx, user) == []
    async with db_sessions() as session:
        for model in (Submission, Mistake, TopicProgress):
            assert await session.scalar(select(func.count()).select_from(model)) == 0
    assert submission.image_key is not None
    assert not await harness.ctx.storage.exists(submission.image_key)


async def test_parallel_answers_complete_quiz_once(db_sessions: Sessions) -> None:
    await consented_user(db_sessions)
    async with db_sessions.begin() as session:
        user = await session.scalar(select(User))
        assert user is not None
        quiz = await quizzes.topic_quiz(session, user, "alg.linear_eq", QuizReason.MANUAL)
        choices = [(item.id, item.correct_index) for item in quiz.items]

    async def answer(item_id: int, choice: int) -> None:
        async with db_sessions.begin() as session:
            await quizzes.answer_item(
                session,
                user_id=user.id,
                quiz_id=quiz.id,
                item_id=item_id,
                choice_index=choice,
                now=utcnow(),
            )

    await asyncio.gather(*(answer(item_id, choice) for item_id, choice in choices))
    async with db_sessions() as session:
        loaded = await quizzes.load_quiz(session, quiz.id, user.id)
        assert loaded.status is QuizStatus.COMPLETED
        assert all(item.answered_index == item.correct_index for item in loaded.items)
        progress = await session.scalar(select(TopicProgress))
        assert progress is not None
        assert progress.correct_total == 3


async def test_parallel_quiz_creation_leaves_one_active(db_sessions: Sessions) -> None:
    await consented_user(db_sessions)

    async def create() -> None:
        async with db_sessions.begin() as session:
            user = await session.scalar(select(User))
            assert user is not None
            await quizzes.topic_quiz(session, user, "alg.linear_eq", QuizReason.MANUAL)

    await asyncio.gather(create(), create())
    async with db_sessions() as session:
        statuses = list((await session.scalars(select(Quiz.status))).all())
    assert sorted(statuses) == [QuizStatus.ACTIVE, QuizStatus.EXPIRED]
