#!/usr/bin/env python3
"""Restricted SSH entrypoint for checked GitHub Actions image releases."""

from __future__ import annotations

import fcntl
import json
import os
import re
import subprocess
import sys
import tempfile
import urllib.request
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import BinaryIO

REPOSITORY = "ghcr.io/nyoqki/preprocessor-idea-fix-2026"
REQUEST = re.compile(r"deploy ([0-9a-f]{40}) (sha256:[0-9a-f]{64})")


@dataclass(frozen=True)
class Credentials:
    user: str
    token: str = field(repr=False)


@dataclass(frozen=True)
class Config:
    root: Path = Path("/srv/yasno")
    backups: Path = Path("/home/admin/backups/yasno-auto")
    ready_url: str = "http://127.0.0.1:8010/readyz"


def parse_request(command: str) -> tuple[str, str]:
    match = REQUEST.fullmatch(command)
    if match is None:
        raise ValueError("Expected: deploy <40-character commit> <sha256 image digest>")
    return match[1], match[2]


def parse_credentials(data: bytes) -> Credentials:
    if len(data) > 16384:
        raise ValueError("Credential payload is too large")
    body = json.loads(data)
    if not isinstance(body, dict):
        raise ValueError("Credential payload must be an object")
    user, token = body.get("registry_user"), body.get("registry_token")
    if not isinstance(user, str) or not re.fullmatch(r"[A-Za-z0-9_\[\]-]{1,128}", user):
        raise ValueError("Invalid registry user")
    if not isinstance(token, str) or not re.fullmatch(r"[A-Za-z0-9_]{20,512}", token):
        raise ValueError("Invalid registry credential")
    return Credentials(user, token)


def run(
    command: list[str],
    *,
    env: dict[str, str] | None = None,
    stdin: str | None = None,
    stdout: BinaryIO | None = None,
    timeout: int = 300,
) -> str:
    result = subprocess.run(  # noqa: S603 - fixed executables; no shell or unvalidated arguments
        command,
        input=stdin,
        text=True,
        stdout=stdout if stdout is not None else subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=True,
        timeout=timeout,
        env=env,
    )
    return result.stdout or ""


def image_of(service: str) -> str:
    return run(["docker", "inspect", f"yasno-{service}-1", "--format", "{{.Image}}"]).strip()


def is_running(service: str) -> bool:
    return (
        run(["docker", "inspect", f"yasno-{service}-1", "--format", "{{.State.Running}}"]).strip()
        == "true"
    )


def compose(config: Config) -> list[str]:
    command = [
        "docker",
        "compose",
        "--project-name",
        "yasno",
        "--project-directory",
        str(config.root),
        "-f",
        str(config.root / "compose.yaml"),
    ]
    poll = config.root / "compose.poll.yaml"
    if poll.is_file():
        command.extend(["-f", str(poll)])
    return command


def services_for(config: Config) -> list[str]:
    services = run([*compose(config), "config", "--services"]).splitlines()
    selected: list[str] = [name for name in ("api", "worker") if name in services]
    if "poller" in services:
        try:
            image_of("poller")
        except subprocess.CalledProcessError:
            pass  # A removed poller means this server uses the webhook.
        else:
            selected.append("poller")
    return selected


def check_ready(config: Config) -> None:
    # Health checks must bypass any workstation/server HTTP proxy.
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(config.ready_url, timeout=10) as response:
        body = json.load(response)
    if body.get("database") != "ok" or body.get("redis") != "ok":
        raise RuntimeError("Application readiness check failed")


def write_json(path: Path, value: dict[str, object]) -> None:
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(value, indent=2) + "\n")
    temporary.replace(path)


def pull_image(commit: str, digest: str, credentials: Credentials) -> tuple[str, str]:
    reference = f"{REPOSITORY}@{digest}"
    with tempfile.TemporaryDirectory(prefix="yasno-registry-") as directory:
        command = ["docker", "--config", directory]
        run(
            [*command, "login", "ghcr.io", "--username", credentials.user, "--password-stdin"],
            stdin=credentials.token + "\n",
            timeout=30,
        )
        run([*command, "pull", reference], timeout=300)
    revision = run(
        [
            "docker",
            "image",
            "inspect",
            reference,
            "--format",
            '{{index .Config.Labels "org.opencontainers.image.revision"}}',
        ]
    ).strip()
    if revision != commit:
        raise ValueError("Image revision does not match the requested commit")
    image_id = run(["docker", "image", "inspect", reference, "--format", "{{.Id}}"])
    return reference, image_id.strip()


def deploy(commit: str, digest: str, credentials: Credentials, config: Config) -> dict[str, object]:
    state_dir = config.root / ".deploy"
    state_dir.mkdir(mode=0o700, exist_ok=True)
    with (state_dir / "lock").open("w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        reference, image_id = pull_image(commit, digest, credentials)
        services = services_for(config)
        if "api" not in services or "worker" not in services:
            raise RuntimeError("Production API and worker services are required")
        previous = {name: image_of(name) for name in services}
        if all(value == image_id for value in previous.values()) and all(
            is_running(name) for name in services
        ):
            check_ready(config)
            return {"status": "already-deployed", "commit": commit, "image": reference}

        timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        backup = config.backups / f"{timestamp}-{commit[:12]}"
        backup.mkdir(mode=0o700, parents=True)
        rollback = backup / "rollback.compose.json"
        write_json(
            rollback, {"services": {name: {"image": image} for name, image in previous.items()}}
        )
        # Pin the previous images so normal image pruning cannot discard the rollback.
        for name, image in previous.items():
            run(["docker", "tag", image, f"yasno:rollback-{timestamp}-{name}"])
        with (backup / "database.dump").open("wb") as dump:
            run(
                [
                    "docker",
                    "exec",
                    "yasno-postgres-1",
                    "sh",
                    "-c",
                    'exec pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Fc',
                ],
                stdout=dump,
                timeout=180,
            )

        command = compose(config)
        environment = {**os.environ, "YASNO_IMAGE": reference}
        switched = False
        try:
            run([*command, "run", "--rm", "--no-deps", "migrate"], env=environment, timeout=180)
            switched = True
            run(
                [
                    *command,
                    "up",
                    "-d",
                    "--no-build",
                    "--no-deps",
                    "--wait",
                    "--wait-timeout",
                    "90",
                    *services,
                ],
                env=environment,
                timeout=180,
            )
            check_ready(config)
            if any(image_of(name) != image_id or not is_running(name) for name in services):
                raise RuntimeError("Application services did not switch to the same release")
            run(["docker", "tag", reference, "yasno:local"])
            result: dict[str, object] = {
                "status": "deployed",
                "commit": commit,
                "image": reference,
                "services": services,
                "backup": str(backup),
                "completed_at": datetime.now(UTC).isoformat(),
            }
            write_json(state_dir / "current.json", result)
            write_json(backup / "release.json", result)
            return result
        except Exception:
            if switched:
                run(
                    [
                        *command,
                        "-f",
                        str(rollback),
                        "up",
                        "-d",
                        "--no-build",
                        "--no-deps",
                        "--wait",
                        "--wait-timeout",
                        "90",
                        *services,
                    ],
                    env=environment,
                    timeout=180,
                )
                check_ready(config)
                run(["docker", "tag", previous["api"], "yasno:local"])
            write_json(backup / "failed.json", {"commit": commit, "containers_restored": switched})
            raise


def main() -> int:
    os.umask(0o077)
    try:
        commit, digest = parse_request(os.environ.get("SSH_ORIGINAL_COMMAND", ""))
        credentials = parse_credentials(sys.stdin.buffer.read(16385))
        result = deploy(commit, digest, credentials, Config())
        print(json.dumps(result))
        return 0
    except Exception as error:
        # Never print stdin, registry credentials, environment, or subprocess stderr.
        print(f"Deployment failed: {type(error).__name__}: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
