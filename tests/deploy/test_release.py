import json
import subprocess
from pathlib import Path
from typing import BinaryIO

import pytest

from deploy import release

COMMIT = "a" * 40
DIGEST = "sha256:" + "b" * 64
CANDIDATE = "sha256:" + "c" * 64
CREDENTIALS = release.Credentials("example-user", "ghs_" + "x" * 40)


class Docker:
    def __init__(self) -> None:
        self.images = {"api": "old-api", "worker": "old-worker", "poller": "old-poller"}
        self.original = self.images.copy()
        self.calls: list[list[str]] = []
        self.migration_fails = False
        self.readiness_fails = False
        self.revision = COMMIT
        self.restored = False
        self.worker_crashes = False

    def run(
        self,
        command: list[str],
        *,
        env: dict[str, str] | None = None,
        stdin: str | None = None,
        stdout: BinaryIO | None = None,
        timeout: int = 300,
    ) -> str:
        self.calls.append(command)
        if command[:2] == ["docker", "inspect"]:
            service = command[2].removeprefix("yasno-").removesuffix("-1")
            if service not in self.images:
                raise subprocess.CalledProcessError(1, command)
            if command[-1] == "{{.State.Running}}":
                if service == "worker" and self.worker_crashes and not self.restored:
                    return "false"
                return "true"
            return self.images[service]
        if command[:3] == ["docker", "image", "inspect"]:
            return self.revision if "revision" in command[-1] else CANDIDATE
        if command[-2:] == ["config", "--services"]:
            return "postgres\nredis\nmigrate\napi\nworker\npoller\n"
        if command[-1] == "migrate" and self.migration_fails:
            raise RuntimeError("Migration failed")
        if "up" in command:
            if any(value.endswith("rollback.compose.json") for value in command):
                self.images = self.original.copy()
                self.restored = True
            else:
                self.images = dict.fromkeys(self.images, CANDIDATE)
        if stdout is not None:
            stdout.write(b"synthetic database backup")
        return ""

    def ready(self, config: release.Config) -> None:
        if self.readiness_fails and not self.restored:
            raise RuntimeError("Readiness failed")


@pytest.fixture
def production(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Docker, release.Config]:
    root = tmp_path / "production"
    root.mkdir()
    (root / "compose.poll.yaml").touch()
    docker = Docker()
    monkeypatch.setattr(release, "run", docker.run)
    monkeypatch.setattr(release, "check_ready", docker.ready)
    return docker, release.Config(root, tmp_path / "backups")


@pytest.mark.parametrize(
    "command",
    [
        "bash",
        f"deploy {COMMIT} {DIGEST}; id",
        f"deploy {COMMIT} ../../image",
        f"deploy {COMMIT} {DIGEST}\n",
        f"deploy {COMMIT[:7]} {DIGEST}",
    ],
)
def test_deploy_key_cannot_execute_other_commands(command: str) -> None:
    with pytest.raises(ValueError, match="Expected"):
        release.parse_request(command)


def test_registry_credential_is_not_part_of_repr_or_command_arguments(
    production: tuple[Docker, release.Config],
) -> None:
    docker, _ = production
    assert CREDENTIALS.token not in repr(CREDENTIALS)
    release.pull_image(COMMIT, DIGEST, CREDENTIALS)
    assert all(CREDENTIALS.token not in " ".join(command) for command in docker.calls)


def test_image_must_belong_to_the_requested_commit(
    production: tuple[Docker, release.Config],
) -> None:
    docker, config = production
    docker.revision = "d" * 40
    with pytest.raises(ValueError, match="revision"):
        release.deploy(COMMIT, DIGEST, CREDENTIALS, config)
    assert docker.images == docker.original
    assert not any(command[-1] == "migrate" for command in docker.calls)


def test_success_updates_all_bot_processes_and_records_release(
    production: tuple[Docker, release.Config],
) -> None:
    docker, config = production
    result = release.deploy(COMMIT, DIGEST, CREDENTIALS, config)
    assert result["status"] == "deployed"
    assert set(docker.images.values()) == {CANDIDATE}
    assert (config.root / ".deploy/current.json").is_file()
    assert len(list(config.backups.glob("*/database.dump"))) == 1
    assert any(command[-1] == "migrate" for command in docker.calls)


def test_failed_readiness_restores_each_previous_service_image(
    production: tuple[Docker, release.Config],
) -> None:
    docker, config = production
    docker.readiness_fails = True
    with pytest.raises(RuntimeError, match="Readiness failed"):
        release.deploy(COMMIT, DIGEST, CREDENTIALS, config)
    assert docker.images == docker.original
    assert docker.restored
    assert not (config.root / ".deploy/current.json").exists()
    assert len(list(config.backups.glob("*/failed.json"))) == 1


def test_failed_migration_keeps_running_release(production: tuple[Docker, release.Config]) -> None:
    docker, config = production
    docker.migration_fails = True
    with pytest.raises(RuntimeError, match="Migration failed"):
        release.deploy(COMMIT, DIGEST, CREDENTIALS, config)
    assert docker.images == docker.original
    assert not docker.restored
    assert not (config.root / ".deploy/current.json").exists()


def test_retry_of_completed_deploy_does_not_repeat_migrations(
    production: tuple[Docker, release.Config],
) -> None:
    docker, config = production
    docker.images = dict.fromkeys(docker.images, CANDIDATE)
    result = release.deploy(COMMIT, DIGEST, CREDENTIALS, config)
    assert result["status"] == "already-deployed"
    assert not any(command[-1] == "migrate" for command in docker.calls)
    assert not config.backups.exists()


def test_webhook_server_does_not_start_a_removed_poller(
    production: tuple[Docker, release.Config],
) -> None:
    docker, config = production
    del docker.images["poller"]
    result = release.deploy(COMMIT, DIGEST, CREDENTIALS, config)
    assert result["services"] == ["api", "worker"]
    assert "poller" not in docker.images


def test_stopped_worker_does_not_count_as_a_successful_release(
    production: tuple[Docker, release.Config],
) -> None:
    docker, config = production
    docker.worker_crashes = True
    with pytest.raises(RuntimeError, match="same release"):
        release.deploy(COMMIT, DIGEST, CREDENTIALS, config)
    assert docker.restored
    assert docker.images == docker.original
    assert not (config.root / ".deploy/current.json").exists()


def test_registry_credentials_accept_long_opaque_github_tokens() -> None:
    token = "v1." + "a-b_c.d=" * 200
    credentials = release.parse_credentials(
        json.dumps({"registry_user": "example-user", "registry_token": token}).encode()
    )
    assert credentials.token == token
    assert token not in repr(credentials)


@pytest.mark.parametrize("suffix", ["\nother-password", "\r", "\x00", " "])
def test_registry_credentials_reject_control_characters_and_whitespace(suffix: str) -> None:
    with pytest.raises(ValueError, match="Invalid registry credential"):
        release.parse_credentials(
            json.dumps(
                {"registry_user": "example-user", "registry_token": "x" * 40 + suffix}
            ).encode()
        )
