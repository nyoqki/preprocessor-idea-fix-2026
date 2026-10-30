from collections.abc import AsyncIterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import SecretStr

from yasno.api import webapp
from yasno.api.deps import get_session
from yasno.api.webapp.auth import current_user, sign_media_token
from yasno.api.webapp.materials import escape_like, make_snippet
from yasno.config import Settings
from yasno.db.models import (
    ConsentStatus,
    Role,
    SchoolClass,
    Submission,
    SubmissionKind,
    SubmissionStatus,
    User,
)
from yasno.media import sniff_image_type
from yasno.storage import LocalStorage

TOKEN = "bot-token"
JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 32


class FakeSession:
    def __init__(self, objects: dict[tuple[type, int], object]) -> None:
        self.objects = objects

    async def get(self, model: type, ident: int) -> object | None:
        return self.objects.get((model, ident))


def make_user(*, role: Role = Role.STUDENT, class_id: int | None = None) -> User:
    return User(
        id=1,
        max_user_id=4242,
        first_name="Аня",
        last_name=None,
        role=role,
        grade=9,
        class_id=class_id,
        consent_status=ConsentStatus.GRANTED,
    )


def make_submission(**overrides: Any) -> Submission:
    values: dict[str, Any] = {
        "id": 10,
        "user_id": 1,
        "kind": SubmissionKind.HOMEWORK,
        "status": SubmissionStatus.DONE,
        "image_key": "submissions/10.jpg",
        "topic_code": "alg.quadratic_eq",
        "created_at": datetime(2026, 11, 2, 18, tzinfo=UTC),
        "finished_at": datetime(2026, 11, 2, 18, 1, tzinfo=UTC),
        "transcription": {
            "task": "Реши уравнение",
            "lines": [
                {"index": 0, "latex": "x^2-5x+6=0", "text": "", "confidence": 0.98},
                {
                    "index": 1,
                    "latex": "D=25+24",
                    "text": "",
                    "confidence": 0.9,
                    "bbox": {"x": 0.1, "y": 0.4, "width": 0.6, "height": 0.08},
                },
                "junk",
            ],
        },
        "analysis": {
            "status": "error",
            "first_error_step": 1,
            "error_type": "sign",
            "hint": "Посмотри на знак перед 4ac.",
        },
    }
    values.update(overrides)
    return Submission(**values)


@pytest.fixture
def objects() -> dict[tuple[type, int], object]:
    return {}


@pytest.fixture
def storage(tmp_path: Path) -> LocalStorage:
    return LocalStorage(tmp_path / "storage")


def build_client(
    user: User, objects: dict[tuple[type, int], object], storage: LocalStorage
) -> TestClient:
    app = FastAPI()
    app.state.settings = Settings(max_bot_token=SecretStr(TOKEN))
    app.state.storage = storage
    app.include_router(webapp.router)

    async def session_override() -> AsyncIterator[FakeSession]:
        yield FakeSession(objects)

    app.dependency_overrides[get_session] = session_override
    app.dependency_overrides[current_user] = lambda: user
    return TestClient(app)


def test_me_without_class(objects: dict[tuple[type, int], object], storage: LocalStorage) -> None:
    response = build_client(make_user(), objects, storage).get("/api/v1/me")
    assert response.status_code == 200
    body = response.json()
    assert body["first_name"] == "Аня"
    assert body["role"] == "student"
    assert body["school_class"] is None


def test_me_with_class(objects: dict[tuple[type, int], object], storage: LocalStorage) -> None:
    objects[(SchoolClass, 3)] = SchoolClass(id=3, title="9Б", grade=9, invite_code="x")
    response = build_client(make_user(class_id=3), objects, storage).get("/api/v1/me")
    assert response.json()["school_class"] == {"id": 3, "title": "9Б", "grade": 9}


def test_teacher_summary_requires_teacher(
    objects: dict[tuple[type, int], object], storage: LocalStorage
) -> None:
    response = build_client(make_user(), objects, storage).get("/api/v1/teacher/summary")
    assert response.status_code == 403
    assert response.json()["detail"] == "teacher_only"


def test_submission_detail_marks_error_line(
    objects: dict[tuple[type, int], object], storage: LocalStorage
) -> None:
    objects[(Submission, 10)] = make_submission()
    response = build_client(make_user(), objects, storage).get("/api/v1/submissions/10")
    assert response.status_code == 200
    body = response.json()
    assert body["topic_title"] == "Квадратные уравнения"
    assert body["error_title"] == "Ошибка в знаке"
    assert body["analysis"]["hint"] == "Посмотри на знак перед 4ac."
    assert [line["is_error"] for line in body["lines"]] == [False, True]
    assert body["error_bbox"] == {"x": 0.1, "y": 0.4, "width": 0.6, "height": 0.08}
    assert body["lines"][0]["display"]
    assert body["image_url"].startswith("/api/v1/submissions/10/image?token=")


def test_submission_detail_hides_foreign_submission(
    objects: dict[tuple[type, int], object], storage: LocalStorage
) -> None:
    objects[(Submission, 10)] = make_submission(user_id=2)
    response = build_client(make_user(), objects, storage).get("/api/v1/submissions/10")
    assert response.status_code == 404


def test_submission_in_progress_has_no_analysis(
    objects: dict[tuple[type, int], object], storage: LocalStorage
) -> None:
    objects[(Submission, 10)] = make_submission(
        status=SubmissionStatus.PROCESSING, analysis=None, transcription=None, image_key=None
    )
    body = build_client(make_user(), objects, storage).get("/api/v1/submissions/10").json()
    assert body["status"] == "processing"
    assert body["analysis"] is None
    assert body["lines"] == []
    assert body["image_url"] is None


async def test_image_requires_valid_token(
    objects: dict[tuple[type, int], object], storage: LocalStorage
) -> None:
    objects[(Submission, 10)] = make_submission()
    await storage.put("submissions/10.jpg", JPEG, "image/jpeg")
    client = build_client(make_user(), objects, storage)
    bad = client.get("/api/v1/submissions/10/image", params={"token": "1.abc"})
    assert bad.status_code == 403
    foreign = sign_media_token("submission-image:11", TOKEN)
    assert client.get("/api/v1/submissions/10/image", params={"token": foreign}).status_code == 403
    token = sign_media_token("submission-image:10", TOKEN)
    good = client.get("/api/v1/submissions/10/image", params={"token": token})
    assert good.status_code == 200
    assert good.headers["content-type"] == "image/jpeg"
    assert good.content == JPEG


def test_missing_image_file_is_404(
    objects: dict[tuple[type, int], object], storage: LocalStorage
) -> None:
    objects[(Submission, 10)] = make_submission()
    token = sign_media_token("submission-image:10", TOKEN)
    response = build_client(make_user(), objects, storage).get(
        "/api/v1/submissions/10/image", params={"token": token}
    )
    assert response.status_code == 404


def test_invalid_cursor_is_rejected(
    objects: dict[tuple[type, int], object], storage: LocalStorage
) -> None:
    response = build_client(make_user(), objects, storage).get(
        "/api/v1/submissions", params={"cursor": "abc"}
    )
    assert response.status_code == 422


@pytest.mark.parametrize(
    ("data", "expected"),
    [
        (JPEG, "image/jpeg"),
        (b"\x89PNG\r\n\x1a\n....", "image/png"),
        (b"RIFF\x00\x00\x00\x00WEBPVP8 ", "image/webp"),
        (b"plain", "application/octet-stream"),
    ],
)
def test_sniff_image_type(data: bytes, expected: str) -> None:
    assert sniff_image_type(data) == expected


def test_snippet_centers_on_match() -> None:
    content = "Начало. " + "слово " * 40 + "Теорема Виета связывает корни. " + "хвост " * 40
    snippet = make_snippet(content, "теорема виета")
    assert "Теорема Виета" in snippet
    assert snippet.startswith("…")
    assert snippet.endswith("…")
    assert len(snippet) < 260


def test_snippet_without_query_takes_beginning() -> None:
    assert make_snippet("  Короткий   конспект ", "") == "Короткий конспект"


def test_escape_like() -> None:
    assert escape_like("50%_a\\b") == "50\\%\\_a\\\\b"
