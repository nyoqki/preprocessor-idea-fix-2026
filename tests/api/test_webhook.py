from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import SecretStr

from tests import factories
from yasno.api import webhook
from yasno.config import Settings


class FakeQueue:
    def __init__(self) -> None:
        self.jobs: dict[str, Any] = {}

    async def enqueue_job(self, name: str, *args: Any, _job_id: str, **_: Any) -> object | None:
        if _job_id in self.jobs:
            return None
        self.jobs[_job_id] = (name, args)
        return object()


@pytest.fixture
def queue() -> FakeQueue:
    return FakeQueue()


@pytest.fixture
def client(queue: FakeQueue) -> TestClient:
    app = FastAPI()
    app.state.settings = Settings(
        max_bot_token=SecretStr("t"), max_webhook_secret=SecretStr("s3cret")
    )
    app.state.queue = queue
    app.include_router(webhook.router)
    return TestClient(app)


def test_rejects_wrong_secret(client: TestClient, queue: FakeQueue) -> None:
    response = client.post(
        "/webhook/max",
        json=factories.dialog_message(),
        headers={"X-Max-Bot-Api-Secret": "nope"},
    )
    assert response.status_code == 401
    assert queue.jobs == {}


def test_enqueues_update_once(client: TestClient, queue: FakeQueue) -> None:
    headers = {"X-Max-Bot-Api-Secret": "s3cret"}
    for _ in range(2):
        response = client.post("/webhook/max", json=factories.dialog_message(), headers=headers)
        assert response.status_code == 200
    assert len(queue.jobs) == 1
    (name, args) = next(iter(queue.jobs.values()))
    assert name == "handle_update"
    assert args[0]["message"]["body"]["mid"] == "mid.1"


def test_malformed_payload_is_acknowledged(client: TestClient, queue: FakeQueue) -> None:
    response = client.post(
        "/webhook/max", content=b"{oops", headers={"X-Max-Bot-Api-Secret": "s3cret"}
    )
    assert response.status_code == 200
    assert queue.jobs == {}
