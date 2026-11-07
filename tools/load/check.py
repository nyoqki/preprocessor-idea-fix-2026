"""Measure an isolated real HTTP/PostgreSQL/Redis stack; never contact real MAX/AI."""

import argparse
import asyncio
import hashlib
import json
import math
import os
import platform
import random
import time
from collections import Counter
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from functools import partial
from pathlib import Path
from typing import Any
from urllib.parse import urlencode
from uuid import uuid4

import httpx
from sqlalchemy import func, select, text

from yasno.api.webapp.auth import sign_init_data
from yasno.db.models import (
    ConsentStatus,
    Mistake,
    Quiz,
    QuizItem,
    QuizReason,
    QuizStatus,
    TopicProgress,
    User,
)
from yasno.db.session import create_engine, create_sessionmaker
from yasno.max.types import Update
from yasno.queue import QUEUE_NAME, create_queue, update_job_id

ROOT = Path(__file__).resolve().parents[2]
COMPOSE = ["docker", "compose", "-f", str(ROOT / "tools/load/compose.yml")]
BASE_URL = "http://127.0.0.1:58001"
DATABASE_URL = "postgresql+asyncpg://yasno:yasno@127.0.0.1:55433/yasno_load"
REDIS_URL = "redis://127.0.0.1:56380/0"
BOT_TOKEN = "load-test-only-not-a-real-token"  # noqa: S105
WEBHOOK_SECRET = "load-test-only-secret"  # noqa: S105
PROFILE_COUNT = 100
REPEATS = 5
TOPICS = ("alg.linear_eq", "alg.quadratic_eq", "arith.fractions")


@dataclass(frozen=True)
class Profile:
    user_id: int
    max_id: int
    authorization: str
    quiz_id: int
    item_ids: tuple[int, ...]


@dataclass(frozen=True)
class Sample:
    milliseconds: float
    status: int
    valid: bool
    operation: str
    error: str | None = None


def percentile(values: list[float], fraction: float) -> float:
    """Nearest-rank percentile; do not hide slow requests behind an average."""
    ordered = sorted(values)
    return round(ordered[max(0, math.ceil(len(ordered) * fraction) - 1)], 2)


def summarize(samples: list[Sample], seconds: float) -> dict[str, Any]:
    latencies = [sample.milliseconds for sample in samples]
    return {
        "requests": len(samples),
        "seconds": round(seconds, 3),
        "requests_per_second": round(len(samples) / seconds, 2),
        "errors": sum(not sample.valid for sample in samples),
        "transport_errors": sum(sample.status == 0 for sample in samples),
        "failure_types": dict(Counter(sample.error for sample in samples if sample.error)),
        "status_counts": dict(sorted(Counter(str(sample.status) for sample in samples).items())),
        "p50_ms": percentile(latencies, 0.5),
        "p95_ms": percentile(latencies, 0.95),
        "p99_ms": percentile(latencies, 0.99),
        "max_ms": round(max(latencies), 2),
        "by_operation": {
            operation: summarize_operation([s for s in samples if s.operation == operation])
            for operation in sorted({sample.operation for sample in samples})
        },
    }


def summarize_operation(samples: list[Sample]) -> dict[str, Any]:
    return {
        "requests": len(samples),
        "errors": sum(not sample.valid for sample in samples),
        "p95_ms": percentile([sample.milliseconds for sample in samples], 0.95),
    }


async def request(
    client: httpx.AsyncClient,
    method: str,
    path: str,
    *,
    operation: str,
    expected: int = 200,
    validate: Callable[[httpx.Response], bool] | None = None,
    **kwargs: Any,
) -> Sample:
    started = time.perf_counter()
    status_code = 0
    valid = False
    error = None
    try:
        response = await client.request(method, path, **kwargs)
        status_code = response.status_code
        valid = status_code == expected and (validate is None or validate(response))
    except (httpx.HTTPError, ValueError, KeyError, TypeError) as exc:
        valid = False
        error = f"{type(exc).__name__}: {exc}"[:160]
    return Sample((time.perf_counter() - started) * 1000, status_code, valid, operation, error)


async def bounded(
    operations: list[Callable[[], Awaitable[Sample]]], concurrency: int
) -> dict[str, Any]:
    semaphore = asyncio.Semaphore(concurrency)

    async def run(operation: Callable[[], Awaitable[Sample]]) -> Sample:
        async with semaphore:
            return await operation()

    started = time.perf_counter()
    samples = await asyncio.gather(*(run(operation) for operation in operations))
    return {"concurrency": concurrency, **summarize(samples, time.perf_counter() - started)}


async def seed() -> list[Profile]:
    engine = create_engine(DATABASE_URL)
    sessions = create_sessionmaker(engine)
    profiles: list[Profile] = []
    first_id = 9_000_000_000_000 + time.time_ns() % 1_000_000_000
    try:
        async with sessions.begin() as session:
            if await session.scalar(text("SELECT current_database()")) != "yasno_load":
                raise RuntimeError("Only the dedicated yasno_load database is allowed")
            for index in range(PROFILE_COUNT):
                max_id = first_id + index
                user = User(
                    max_user_id=max_id,
                    first_name=f"Load {index}",
                    grade=9,
                    consent_status=ConsentStatus.GRANTED,
                )
                session.add(user)
                await session.flush()
                for topic in TOPICS:
                    session.add(
                        TopicProgress(
                            user_id=user.id,
                            topic_code=topic,
                            mistakes_total=2,
                            correct_total=0,
                            last_mistake_at=datetime.now(UTC),
                        )
                    )
                    session.add_all(
                        Mistake(user_id=user.id, topic_code=topic, error_type="sign")
                        for _ in range(2)
                    )
                quiz = Quiz(user_id=user.id, reason=QuizReason.REVIEW)
                quiz.items = [
                    QuizItem(
                        position=position,
                        topic_code="alg.linear_eq",
                        prompt="2x = 4. Найди x.",
                        choices=[{"text": "x = 2"}, {"text": "x = 4", "error_type": "sign"}],
                        correct_index=0,
                    )
                    for position in range(3)
                ]
                session.add(quiz)
                await session.flush()
                pairs = {
                    "auth_date": str(int(time.time())),
                    "user": json.dumps({"id": max_id, "first_name": user.first_name}),
                }
                pairs["hash"] = sign_init_data(pairs, BOT_TOKEN)
                profiles.append(
                    Profile(
                        user.id,
                        max_id,
                        "tma " + urlencode(pairs),
                        quiz.id,
                        tuple(item.id for item in quiz.items),
                    )
                )
    finally:
        await engine.dispose()
    return profiles


async def read_stage(
    client: httpx.AsyncClient, profiles: list[Profile], concurrency: int, duration: float
) -> dict[str, Any]:
    started = time.perf_counter()
    deadline = started + duration
    paths = ("/api/v1/me", "/api/v1/gaps", "/api/v1/quizzes/active")

    async def worker(number: int) -> list[Sample]:
        samples: list[Sample] = []
        index = number
        while time.perf_counter() < deadline:
            profile = profiles[index % len(profiles)]
            path = paths[(index // len(profiles) + number) % len(paths)]

            def validate(
                response: httpx.Response, path: str = path, profile: Profile = profile
            ) -> bool:
                body = response.json()
                if path.endswith("/me"):
                    return bool(body["id"] == profile.user_id)
                if path.endswith("/gaps"):
                    return len(body["topics"]) == len(TOPICS) and all(
                        topic["mistakes_total"] == 2 for topic in body["topics"]
                    )
                return bool(body["quiz"]["id"] == profile.quiz_id)

            samples.append(
                await request(
                    client,
                    "GET",
                    path,
                    operation=path,
                    headers={"Authorization": profile.authorization},
                    validate=validate,
                )
            )
            index += 1
        return samples

    groups = await asyncio.gather(*(worker(number) for number in range(concurrency)))
    samples = [sample for group in groups for sample in group]
    return {"concurrency": concurrency, **summarize(samples, time.perf_counter() - started)}


async def answer_stage(client: httpx.AsyncClient, profiles: list[Profile]) -> dict[str, Any]:
    jobs = [(profile, item_id) for profile in profiles for item_id in profile.item_ids] * REPEATS
    random.Random(42).shuffle(jobs)  # noqa: S311

    async def answer(profile: Profile, item_id: int) -> Sample:
        return await request(
            client,
            "POST",
            f"/api/v1/quizzes/{profile.quiz_id}/items/{item_id}/answer",
            operation="answer/replay",
            headers={"Authorization": profile.authorization},
            json={"choice_index": 0},
            validate=lambda r: r.json()["is_correct"] is True and r.json()["chosen_index"] == 0,
        )

    result = await bounded(
        [partial(answer, profile, item) for profile, item in jobs], concurrency=50
    )
    engine = create_engine(DATABASE_URL)
    sessions = create_sessionmaker(engine)
    try:
        async with sessions() as session:
            completed = await session.scalar(
                select(func.count())
                .select_from(Quiz)
                .where(
                    Quiz.id.in_([p.quiz_id for p in profiles]), Quiz.status == QuizStatus.COMPLETED
                )
            )
            counters = list(
                (
                    await session.scalars(
                        select(TopicProgress.correct_total).where(
                            TopicProgress.user_id.in_([p.user_id for p in profiles]),
                            TopicProgress.topic_code == "alg.linear_eq",
                        )
                    )
                ).all()
            )
            mistakes = await session.scalar(
                select(func.count())
                .select_from(Mistake)
                .where(Mistake.user_id.in_([p.user_id for p in profiles]))
            )
        result["invariants"] = {
            "completed_quizzes": completed,
            "expected_completed_quizzes": len(profiles),
            "correct_total": sum(counters),
            "expected_correct_total": len(profiles) * 3,
            "every_user_has_exactly_three_successes": len(counters) == len(profiles)
            and all(counter == 3 for counter in counters),
            "mistake_records_unchanged": mistakes == len(profiles) * len(TOPICS) * 2,
        }
    finally:
        await engine.dispose()
    return result


def update_payload(prefix: str, index: int) -> dict[str, Any]:
    return {
        "update_type": "message_created",
        "timestamp": 1_790_000_000_000,
        "message": {
            "sender": {"user_id": 100, "first_name": "Load", "is_bot": False},
            "recipient": {"chat_id": 555, "chat_type": "dialog", "user_id": 999},
            "timestamp": 1_790_000_000_000,
            "body": {"mid": f"load.{prefix}.{index}", "seq": index, "text": "synthetic"},
        },
    }


async def webhook_stage(client: httpx.AsyncClient) -> dict[str, Any]:
    prefix = uuid4().hex
    payloads = [update_payload(prefix, index) for index in range(100)]
    expected = {update_job_id(Update.model_validate(payload)) for payload in payloads}
    queue = await create_queue(REDIS_URL)
    try:
        before = set(await queue.zrange(QUEUE_NAME, 0, -1))

        async def deliver(payload: dict[str, Any]) -> Sample:
            return await request(
                client,
                "POST",
                "/webhook/max",
                operation="webhook/replay",
                json=payload,
                headers={"X-Max-Bot-Api-Secret": WEBHOOK_SECRET},
            )

        result = await bounded(
            [partial(deliver, payload) for payload in payloads for _ in range(10)], concurrency=100
        )
        added = set(await queue.zrange(QUEUE_NAME, 0, -1)) - before
        result["invariants"] = {
            "unique_updates": len(expected),
            "added_jobs": len(added),
            "exact_job_ids_match": {item.decode() for item in added} == expected,
            "worker_running": False,
        }
        return result
    finally:
        await queue.aclose()


async def compose_command(*arguments: str) -> None:
    process = await asyncio.create_subprocess_exec(*COMPOSE, *arguments)
    if await process.wait():
        raise RuntimeError("Isolated compose command failed")


async def command_output(*arguments: str) -> str:
    process = await asyncio.create_subprocess_exec(
        *arguments, cwd=ROOT, stdout=asyncio.subprocess.PIPE
    )
    output, _ = await process.communicate()
    if process.returncode:
        raise RuntimeError("Metadata command failed")
    return output.decode().strip()


async def redis_outage(client: httpx.AsyncClient) -> dict[str, Any]:
    await compose_command("stop", "redis")
    try:
        ready = await request(client, "GET", "/readyz", operation="readiness", expected=503)
        webhook = await request(
            client,
            "POST",
            "/webhook/max",
            operation="webhook_without_redis",
            expected=503,
            json=update_payload(uuid4().hex, 0),
            headers={"X-Max-Bot-Api-Secret": WEBHOOK_SECRET},
        )
    finally:
        restarted = time.perf_counter()
        await compose_command("start", "redis")
    recovered = False
    while time.perf_counter() - restarted < 30:
        probe = await request(client, "GET", "/readyz", operation="readiness")
        if probe.valid:
            recovered = True
            break
        await asyncio.sleep(0.25)
    queued_after = await request(
        client,
        "POST",
        "/webhook/max",
        operation="webhook_after_redis_restart",
        json=update_payload(uuid4().hex, 0),
        headers={"X-Max-Bot-Api-Secret": WEBHOOK_SECRET},
    )
    return {
        "readiness_during_outage": ready.status,
        "webhook_during_outage": webhook.status,
        "expected_statuses_received": ready.valid and webhook.valid,
        "recovered_without_api_restart": recovered,
        "recovery_seconds": round(time.perf_counter() - restarted, 3),
        "webhook_after_recovery": queued_after.status,
        "passed": ready.valid and webhook.valid and recovered and queued_after.valid,
    }


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--duration", type=float, default=20)
    parser.add_argument("--concurrency", type=int, nargs="+", default=[5, 20, 50, 100])
    parser.add_argument("--fault-test", action="store_true")
    parser.add_argument("--keepalive-expiry", type=float, default=2)
    parser.add_argument("--output", type=Path, default=Path("docs/load-results.json"))
    args = parser.parse_args()
    if (
        args.duration < 1
        or args.keepalive_expiry <= 0
        or any(c < 1 or c > 200 for c in args.concurrency)
    ):
        parser.error("duration must be >= 1; keepalive expiry > 0; concurrency between 1 and 200")
    api_container = await command_output(*COMPOSE, "ps", "-q", "api")
    report: dict[str, Any] = {
        "checked_at_utc": datetime.now(UTC).isoformat(),
        "driver_sha256": hashlib.sha256(
            await asyncio.to_thread(Path(__file__).read_bytes)
        ).hexdigest(),
        "compose_sha256": hashlib.sha256(
            await asyncio.to_thread((ROOT / "tools/load/compose.yml").read_bytes)
        ).hexdigest(),
        "application_commit": await command_output("git", "rev-parse", "HEAD"),
        "image_id": await command_output(
            "docker", "inspect", "--format", "{{.Image}}", api_container
        ),
        "environment": {
            "python": platform.python_version(),
            "host_cpus": os.cpu_count(),
            "platform": platform.system(),
            "api_limits": {"cpus": 2, "memory_mib": 1024, "processes": 1},
            "postgres_limits": {"cpus": 1, "memory_mib": 512},
            "redis_limits": {"cpus": 0.5, "memory_mib": 128},
            "target": BASE_URL,
            "real_database_and_redis": True,
            "max_api_url": "http://127.0.0.1:9",
            "real_max_and_ai_calls": 0,
        },
        "model": "closed: fixed concurrent requests, no think time, no fixed arrival rate",
        "client_connection_pool": {
            "max_connections": 200,
            "max_keepalive_connections": 200,
            "keepalive_expiry_seconds": args.keepalive_expiry,
            "automatic_retries": 0,
        },
        "fixtures": {
            "synthetic_users": PROFILE_COUNT,
            "topics_per_user": len(TOPICS),
            "mistakes_per_topic": 2,
            "quizzes": PROFILE_COUNT,
            "items_per_quiz": 3,
            "copies_of_each_answer": REPEATS,
        },
        "thresholds_declared_before_run": {
            "all_stages_errors": 0,
            "read_stages_at_concurrency_up_to_20_p95_ms": 1000,
            "stress_stages_50_and_100": "exploratory latency; zero errors and intact invariants",
        },
        "limits": [
            "Local loopback; no public HTTPS/MAX client/AI/image processing",
            "Short sustained stages, not a soak or a demonstrated production capacity",
            "Closed model throughput decreases if the service slows down",
        ],
    }
    timeout = httpx.Timeout(10, connect=3)
    async with httpx.AsyncClient(
        base_url=BASE_URL,
        trust_env=False,
        timeout=timeout,
        limits=httpx.Limits(
            max_connections=200,
            max_keepalive_connections=200,
            keepalive_expiry=args.keepalive_expiry,
        ),
    ) as client:
        for _ in range(40):
            probe = await request(client, "GET", "/readyz", operation="startup")
            if probe.valid:
                break
            await asyncio.sleep(0.25)
        (await client.get("/readyz")).raise_for_status()
        profiles = await seed()
        await read_stage(client, profiles, concurrency=5, duration=2)
        stages = []
        for concurrency in args.concurrency:
            result = await read_stage(client, profiles, concurrency, args.duration)
            stages.append(result)
            print(json.dumps({"read_stage": result}, ensure_ascii=False), flush=True)
        report["read_stages"] = stages
        report["answers"] = await answer_stage(client, profiles)
        print(json.dumps({"answers": report["answers"]}, ensure_ascii=False), flush=True)
        report["webhooks"] = await webhook_stage(client)
        print(json.dumps({"webhooks": report["webhooks"]}, ensure_ascii=False), flush=True)
        if args.fault_test:
            report["redis_outage"] = await redis_outage(client)
        report["readyz_after"] = (await client.get("/readyz")).json()
    runtime = json.loads(
        await command_output("docker", "inspect", "--format", "{{json .State}}", api_container)
    )
    report["api_after"] = {
        "running": runtime["Running"],
        "oom_killed": runtime["OOMKilled"],
        "restart_count": int(
            await command_output(
                "docker", "inspect", "--format", "{{.RestartCount}}", api_container
            )
        ),
    }
    report["passed"] = (
        all(s["errors"] == 0 for s in stages)
        and all(s["p95_ms"] <= 1000 for s in stages if s["concurrency"] <= 20)
        and report["answers"]["errors"] == 0
        and report["answers"]["invariants"]["every_user_has_exactly_three_successes"]
        and report["answers"]["invariants"]["mistake_records_unchanged"]
        and report["answers"]["invariants"]["completed_quizzes"] == len(profiles)
        and report["webhooks"]["errors"] == 0
        and report["webhooks"]["invariants"]["exact_job_ids_match"]
        and (not args.fault_test or report["redis_outage"]["passed"])
        and report["readyz_after"] == {"database": "ok", "redis": "ok"}
        and report["api_after"] == {"running": True, "oom_killed": False, "restart_count": 0}
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(f"Report: {args.output}; passed={report['passed']}", flush=True)
    if not report["passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    asyncio.run(main())
