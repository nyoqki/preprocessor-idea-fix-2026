from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr

from yasno.api.app import create_app
from yasno.config import Settings

TOKEN = "bot-token"


@pytest.fixture
def dist(tmp_path: Path) -> Path:
    root = tmp_path / "dist"
    (root / "assets").mkdir(parents=True)
    (root / "index.html").write_text("<!doctype html><title>Ясно</title>", encoding="utf-8")
    (root / "assets" / "index-abc123.js").write_text("console.log(1)", encoding="utf-8")
    (root / "favicon.svg").write_text("<svg/>", encoding="utf-8")
    (tmp_path / "secret.txt").write_text("secret", encoding="utf-8")
    return root


@pytest.fixture
def spa_client(dist: Path) -> TestClient:
    return TestClient(create_app(Settings(max_bot_token=SecretStr(TOKEN), webapp_dist_dir=dist)))


def test_spa_index_is_not_cached(spa_client: TestClient) -> None:
    response = spa_client.get("/")
    assert response.status_code == 200
    assert "Ясно" in response.text
    assert response.headers["cache-control"] == "no-cache"
    csp = response.headers["content-security-policy"]
    assert "frame-ancestors" in csp
    assert "https://st.max.ru" in csp
    assert response.headers["x-content-type-options"] == "nosniff"
    assert "x-frame-options" not in response.headers


def test_spa_client_routes_fall_back_to_index(spa_client: TestClient) -> None:
    response = spa_client.get("/quiz/5")
    assert response.status_code == 200
    assert "Ясно" in response.text


def test_spa_hashed_assets_are_immutable(spa_client: TestClient) -> None:
    response = spa_client.get("/assets/index-abc123.js")
    assert response.status_code == 200
    assert "immutable" in response.headers["cache-control"]
    assert spa_client.get("/assets/missing.js").status_code == 404
    assert spa_client.get("/favicon.svg").headers["cache-control"].startswith("public")


def test_spa_does_not_shadow_backend_routes(spa_client: TestClient) -> None:
    assert spa_client.get("/healthz").json() == {"status": "ok"}
    api = spa_client.get("/api/v1/unknown")
    assert api.status_code == 404
    assert api.headers["cache-control"] == "no-store"
    assert spa_client.get("/api/v1/me").status_code == 401
    assert spa_client.get("/webhook/max").status_code == 404


def test_spa_blocks_path_traversal(spa_client: TestClient) -> None:
    response = spa_client.get("/..%2fsecret.txt")
    assert "secret" not in response.text


def test_spa_is_skipped_without_dist(tmp_path: Path) -> None:
    app = create_app(Settings(max_bot_token=SecretStr(TOKEN), webapp_dist_dir=tmp_path / "none"))
    assert TestClient(app).get("/").status_code == 404
