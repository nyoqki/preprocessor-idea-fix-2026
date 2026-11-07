from datetime import UTC, datetime, timedelta
from typing import Annotated
from urllib.parse import quote

import orjson
import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient
from pydantic import SecretStr

from yasno.api.webapp.auth import (
    InitData,
    InitDataError,
    parse_init_data,
    read_init_data,
    sign_init_data,
    sign_media_token,
    verify_media_token,
)
from yasno.config import Settings

TOKEN = "bot-token"
NOW = datetime(2026, 11, 3, 12, tzinfo=UTC)
USER = {"id": 4242, "first_name": "Аня", "last_name": "Петрова", "language_code": "ru"}


def build_init_data(
    *,
    token: str = TOKEN,
    auth_date: datetime = NOW,
    user: dict[str, object] | None = None,
    extra: dict[str, str] | None = None,
) -> str:
    pairs = {
        "auth_date": str(int(auth_date.timestamp())),
        "query_id": "q-1",
        "user": orjson.dumps(user or USER).decode(),
        "start_param": "quiz_7",
        **(extra or {}),
    }
    signature = sign_init_data(pairs, token)
    encoded = "&".join(f"{key}={quote(value, safe='')}" for key, value in pairs.items())
    return f"{encoded}&hash={signature}"


def parse(raw: str, *, ttl: int = 3600) -> InitData:
    return parse_init_data(raw, TOKEN, ttl_seconds=ttl, now=NOW)


def test_valid_init_data_is_parsed() -> None:
    data = parse(build_init_data())
    assert data.user.id == 4242
    assert data.user.first_name == "Аня"
    assert data.user.last_name == "Петрова"
    assert data.start_param == "quiz_7"
    assert data.auth_date == NOW


def test_hash_position_does_not_matter() -> None:
    raw = build_init_data()
    body, _, signature = raw.rpartition("&hash=")
    data = parse(f"hash={signature}&{body}")
    assert data.user.id == 4242


def test_wrong_bot_token_is_rejected() -> None:
    with pytest.raises(InitDataError):
        parse(build_init_data(token="other-token"))


def test_tampered_value_is_rejected() -> None:
    raw = build_init_data().replace("quiz_7", "quiz_8")
    with pytest.raises(InitDataError):
        parse(raw)


def test_expired_init_data_is_rejected() -> None:
    with pytest.raises(InitDataError, match="expired"):
        parse(build_init_data(auth_date=NOW - timedelta(hours=2)))


def test_future_init_data_is_rejected() -> None:
    with pytest.raises(InitDataError, match="future"):
        parse(build_init_data(auth_date=NOW + timedelta(hours=1)))


def test_duplicate_hash_is_rejected() -> None:
    raw = build_init_data()
    signature = raw.rpartition("&hash=")[2]
    with pytest.raises(InitDataError, match="exactly once"):
        parse(f"{raw}&hash={signature}")


def test_missing_hash_is_rejected() -> None:
    raw = build_init_data().rpartition("&hash=")[0]
    with pytest.raises(InitDataError, match="exactly once"):
        parse(raw)


def test_duplicate_key_is_rejected() -> None:
    raw = build_init_data()
    with pytest.raises(InitDataError, match="duplicate"):
        parse(f"query_id=q-2&{raw}")


@pytest.mark.parametrize("raw", ["", "garbage", "a=1&&hash=x", "=1&hash=x"])
def test_malformed_init_data_is_rejected(raw: str) -> None:
    with pytest.raises(InitDataError):
        parse(raw)


def test_user_is_required() -> None:
    pairs = {"auth_date": str(int(NOW.timestamp()))}
    raw = f"auth_date={pairs['auth_date']}&hash={sign_init_data(pairs, TOKEN)}"
    with pytest.raises(InitDataError, match="user"):
        parse(raw)


def test_media_token_roundtrip() -> None:
    token = sign_media_token("submission-image:5", TOKEN, now=NOW)
    assert verify_media_token(token, "submission-image:5", TOKEN, now=NOW)
    assert verify_media_token(token, "submission-image:5", TOKEN, now=NOW + timedelta(hours=1))
    assert not verify_media_token(token, "submission-image:6", TOKEN, now=NOW)
    assert not verify_media_token(token, "submission-image:5", "other", now=NOW)
    assert not verify_media_token(token, "submission-image:5", TOKEN, now=NOW + timedelta(days=1))
    assert not verify_media_token("nope", "submission-image:5", TOKEN, now=NOW)


def test_media_token_is_stable_within_an_hour() -> None:
    first = sign_media_token("s", TOKEN, now=NOW)
    second = sign_media_token("s", TOKEN, now=NOW + timedelta(minutes=30))
    assert first == second


@pytest.fixture
def auth_client() -> TestClient:
    app = FastAPI()
    app.state.settings = Settings(max_bot_token=SecretStr(TOKEN))

    @app.get("/whoami")
    def whoami(data: Annotated[InitData, Depends(read_init_data)]) -> dict[str, object]:
        return {"id": data.user.id, "start_param": data.start_param}

    return TestClient(app)


def test_dependency_accepts_tma_header(auth_client: TestClient) -> None:
    raw = build_init_data(auth_date=datetime.now(UTC))
    response = auth_client.get("/whoami", headers={"Authorization": f"tma {raw}"})
    assert response.status_code == 200
    assert response.json() == {"id": 4242, "start_param": "quiz_7"}


@pytest.mark.parametrize(
    "header",
    [None, "Bearer abc", "tma ", "tma auth_date=1&hash=00"],
)
def test_dependency_rejects_bad_headers(auth_client: TestClient, header: str | None) -> None:
    headers = {"Authorization": header} if header is not None else {}
    response = auth_client.get("/whoami", headers=headers)
    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "tma"


@pytest.mark.parametrize("timestamp", ["99999999999999999999", "-99999999999999999999"])
def test_signed_out_of_range_timestamp_is_rejected(timestamp: str) -> None:
    with pytest.raises(InitDataError):
        parse(build_init_data(extra={"auth_date": timestamp}))


def test_non_ascii_signature_is_rejected_without_server_error() -> None:
    raw = build_init_data().rpartition("&hash=")[0]
    with pytest.raises(InitDataError):
        parse(raw + "&hash=%D1%8F")
    token = sign_media_token("scope", TOKEN, now=NOW)
    assert not verify_media_token(token.rpartition(".")[0] + ".я", "scope", TOKEN, now=NOW)
