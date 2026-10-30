from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Any

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from pydantic import SecretStr
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from tests.api.test_webapp_auth import build_init_data
from yasno.api import webapp
from yasno.api.deps import get_session
from yasno.api.webapp.auth import current_user
from yasno.config import Settings
from yasno.db.models import (
    Material,
    Mistake,
    Quiz,
    QuizItem,
    QuizReason,
    Role,
    SchoolClass,
    Submission,
    SubmissionKind,
    SubmissionStatus,
    TopicProgress,
    User,
)
from yasno.math.errors import ErrorType
from yasno.services.progress import record_mistake, record_success
from yasno.storage import LocalStorage

pytestmark = pytest.mark.db

NOW = datetime(2026, 11, 3, 12, tzinfo=UTC)
Sessions = async_sessionmaker[AsyncSession]


async def add_user(
    sessions: Sessions,
    max_user_id: int,
    *,
    first_name: str = "Аня",
    role: Role = Role.STUDENT,
    class_id: int | None = None,
) -> User:
    async with sessions() as session:
        user = User(max_user_id=max_user_id, first_name=first_name, role=role, class_id=class_id)
        session.add(user)
        await session.commit()
        return user


async def add_class(sessions: Sessions, title: str = "9Б") -> SchoolClass:
    async with sessions() as session:
        school_class = SchoolClass(title=title, grade=9, invite_code=f"inv-{title}")
        session.add(school_class)
        await session.commit()
        return school_class


def make_client(sessions: Sessions, user: User | None, tmp_storage: LocalStorage) -> AsyncClient:
    app = FastAPI()
    app.state.settings = Settings(max_bot_token=SecretStr("bot-token"))
    app.state.storage = tmp_storage
    app.include_router(webapp.router)

    async def session_override() -> AsyncIterator[AsyncSession]:
        async with sessions() as session:
            yield session

    app.dependency_overrides[get_session] = session_override
    if user is not None:
        app.dependency_overrides[current_user] = lambda: user
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


@pytest.fixture
def storage(tmp_path: Any) -> LocalStorage:
    return LocalStorage(tmp_path)


async def test_init_data_upserts_user(db_sessions: Sessions, storage: LocalStorage) -> None:
    client = make_client(db_sessions, None, storage)
    raw = build_init_data(auth_date=datetime.now(UTC))
    response = await client.get("/api/v1/me", headers={"Authorization": f"tma {raw}"})
    assert response.status_code == 200
    assert response.json()["first_name"] == "Аня"
    async with db_sessions() as session:
        user = await session.scalar(select(User).where(User.max_user_id == 4242))
    assert user is not None
    assert user.last_name == "Петрова"


async def test_gap_map_with_error_types(db_sessions: Sessions, storage: LocalStorage) -> None:
    user = await add_user(db_sessions, 1)
    async with db_sessions() as session:
        for error_type in (ErrorType.SIGN, ErrorType.SIGN, ErrorType.ARITHMETIC):
            await record_mistake(
                session,
                user_id=user.id,
                topic_code="alg.quadratic_eq",
                error_type=error_type,
                now=NOW,
            )
        await record_mistake(
            session,
            user_id=user.id,
            topic_code="arith.fractions",
            error_type=ErrorType.FRACTIONS,
            now=NOW,
        )
        for _ in range(4):
            await record_success(session, user_id=user.id, topic_code="arith.fractions", now=NOW)
        await session.commit()
    body = (await make_client(db_sessions, user, storage).get("/api/v1/gaps")).json()
    assert body["summary"] == {"weak": 1, "improving": 0, "solid": 1}
    first, second = body["topics"]
    assert first["code"] == "alg.quadratic_eq"
    assert first["status"] == "weak"
    assert first["mistakes_total"] == 3
    assert first["error_types"][0] == {"code": "sign", "title": "Ошибка в знаке", "count": 2}
    assert second["status"] == "solid"


async def test_submissions_are_paginated(db_sessions: Sessions, storage: LocalStorage) -> None:
    user = await add_user(db_sessions, 1)
    other = await add_user(db_sessions, 2)
    async with db_sessions() as session:
        for index in range(3):
            session.add(
                Submission(
                    user_id=user.id,
                    kind=SubmissionKind.HOMEWORK,
                    status=SubmissionStatus.DONE,
                    topic_code="alg.roots",
                    analysis={"status": "error", "first_error_step": index, "error_type": "roots"},
                )
            )
        session.add(Submission(user_id=user.id, kind=SubmissionKind.MATERIAL))
        session.add(Submission(user_id=other.id, kind=SubmissionKind.HOMEWORK))
        await session.commit()
    client = make_client(db_sessions, user, storage)
    page = (await client.get("/api/v1/submissions", params={"limit": 2})).json()
    assert [item["first_error_step"] for item in page["items"]] == [2, 1]
    assert page["next_cursor"] is not None
    rest = (
        await client.get("/api/v1/submissions", params={"limit": 2, "cursor": page["next_cursor"]})
    ).json()
    assert [item["first_error_step"] for item in rest["items"]] == [0]
    assert rest["next_cursor"] is None
    assert rest["items"][0]["error_title"] == "Свойства корней"


async def make_quiz(sessions: Sessions, user: User) -> Quiz:
    async with sessions() as session:
        quiz = Quiz(user_id=user.id, reason=QuizReason.REVIEW)
        quiz.items = [
            QuizItem(
                position=index,
                topic_code="alg.quadratic_eq",
                prompt=f"Вопрос {index + 1}",
                choices=[
                    {"text": "x = 2", "error_type": "sign", "explanation": "Проверь знак"},
                    {"text": "x = 3"},
                    {"text": "x = -3", "error_type": "arithmetic"},
                    {"text": "нет корней", "error_type": "formula"},
                ],
                correct_index=1,
            )
            for index in range(2)
        ]
        session.add(quiz)
        await session.commit()
        return quiz


async def test_quiz_answer_flow(db_sessions: Sessions, storage: LocalStorage) -> None:
    user = await add_user(db_sessions, 1)
    quiz = await make_quiz(db_sessions, user)
    first, second = sorted(quiz.items, key=lambda item: item.position)
    client = make_client(db_sessions, user, storage)

    active = (await client.get("/api/v1/quizzes/active")).json()["quiz"]
    assert active["id"] == quiz.id
    assert active["total"] == 2
    detail = (await client.get(f"/api/v1/quizzes/{quiz.id}")).json()
    assert detail["items"][0]["correct_index"] is None
    assert [choice["text"] for choice in detail["items"][0]["choices"]][1] == "x = 3"

    url = f"/api/v1/quizzes/{quiz.id}/items/{first.id}/answer"
    wrong = (await client.post(url, json={"choice_index": 0})).json()
    assert wrong["is_correct"] is False
    assert wrong["correct_index"] == 1
    assert wrong["explanation"] == "Проверь знак"
    assert wrong["quiz_status"] == "active"

    repeat = (await client.post(url, json={"choice_index": 1})).json()
    assert repeat["already_answered"] is True
    assert repeat["chosen_index"] == 0
    assert repeat["is_correct"] is False

    done = (
        await client.post(
            f"/api/v1/quizzes/{quiz.id}/items/{second.id}/answer", json={"choice_index": 1}
        )
    ).json()
    assert done["is_correct"] is True
    assert done["quiz_status"] == "completed"
    assert (done["answered"], done["total"], done["correct"]) == (2, 2, 1)
    assert (await client.get("/api/v1/quizzes/active")).json()["quiz"] is None

    async with db_sessions() as session:
        mistakes = (await session.execute(select(Mistake))).scalars().all()
        progress = await session.get(TopicProgress, (user.id, "alg.quadratic_eq"))
    assert [(m.error_type, m.quiz_item_id) for m in mistakes] == [("sign", first.id)]
    assert progress is not None
    assert (progress.mistakes_total, progress.correct_total) == (1, 1)


async def test_quiz_rejects_bad_choice_and_foreign_user(
    db_sessions: Sessions, storage: LocalStorage
) -> None:
    owner = await add_user(db_sessions, 1)
    stranger = await add_user(db_sessions, 2)
    quiz = await make_quiz(db_sessions, owner)
    item = quiz.items[0]
    url = f"/api/v1/quizzes/{quiz.id}/items/{item.id}/answer"
    owner_client = make_client(db_sessions, owner, storage)
    assert (await owner_client.post(url, json={"choice_index": 9})).status_code == 422
    stranger_client = make_client(db_sessions, stranger, storage)
    assert (await stranger_client.get(f"/api/v1/quizzes/{quiz.id}")).status_code == 404
    assert (await stranger_client.post(url, json={"choice_index": 1})).status_code == 404


async def test_materials_search(db_sessions: Sessions, storage: LocalStorage) -> None:
    school_class = await add_class(db_sessions)
    other_class = await add_class(db_sessions, "10А")
    user = await add_user(db_sessions, 1, class_id=school_class.id)
    loner = await add_user(db_sessions, 2)
    async with db_sessions() as session:
        session.add_all(
            [
                Material(
                    class_id=school_class.id,
                    title="Конспект",
                    content="Теорема Виета: сумма корней равна -b/a, произведение c/a.",
                    topic_codes=["alg.quadratic_eq"],
                ),
                Material(class_id=school_class.id, title="Дроби", content="Скидка 50% на всё"),
                Material(class_id=other_class.id, title="Чужое", content="Теорема Виета"),
            ]
        )
        await session.commit()
    client = make_client(db_sessions, user, storage)
    found = (await client.get("/api/v1/materials", params={"q": "виета"})).json()
    assert found["has_class"] is True
    assert [item["title"] for item in found["items"]] == ["Конспект"]
    assert "Теорема Виета" in found["items"][0]["snippet"]
    assert found["items"][0]["topic_titles"] == ["Квадратные уравнения"]
    percent = (await client.get("/api/v1/materials", params={"q": "50%"})).json()
    assert [item["title"] for item in percent["items"]] == ["Дроби"]
    underscore = (await client.get("/api/v1/materials", params={"q": "_"})).json()
    assert underscore["items"] == []
    assert len((await client.get("/api/v1/materials")).json()["items"]) == 2
    alone = (await make_client(db_sessions, loner, storage).get("/api/v1/materials")).json()
    assert alone == {"has_class": False, "items": [], "next_cursor": None}


async def test_teacher_summary_is_anonymous(db_sessions: Sessions, storage: LocalStorage) -> None:
    school_class = await add_class(db_sessions)
    teacher = await add_user(db_sessions, 1, role=Role.TEACHER, class_id=school_class.id)
    students = [
        await add_user(
            db_sessions, 10 + index, first_name=f"Ученик{index}", class_id=school_class.id
        )
        for index in range(3)
    ]
    outsider = await add_user(db_sessions, 99)
    async with db_sessions() as session:
        for student in [*students[:2], outsider]:
            await record_mistake(
                session,
                user_id=student.id,
                topic_code="alg.quadratic_eq",
                error_type=ErrorType.SIGN,
                now=NOW,
            )
        await session.commit()
    response = await make_client(db_sessions, teacher, storage).get("/api/v1/teacher/summary")
    assert response.status_code == 200
    body = response.json()
    assert body["students_total"] == 3
    assert body["students_with_gaps"] == 2
    assert body["topics"] == [
        {
            "code": "alg.quadratic_eq",
            "title": "Квадратные уравнения",
            "weak": 2,
            "improving": 0,
            "solid": 0,
            "top_error_type": {"code": "sign", "title": "Ошибка в знаке", "count": 2},
        }
    ]
    assert "Ученик" not in response.text
    async with db_sessions() as session:
        total = await session.scalar(select(func.count()).select_from(Mistake))
    assert total == 3
