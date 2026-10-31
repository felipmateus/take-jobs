"""UT-110: the Compose contract of `_spec.md` > System Architecture."""

import json
import subprocess
from pathlib import Path

import pytest

from tests.static.support import DOCKER_AVAILABLE, clean_environment, compose_config, load_compose

HEALTHCHECK = ["CMD-SHELL", "pg_isready -U $$POSTGRES_USER -d $$POSTGRES_DB"]


@pytest.fixture(scope="module")
def compose() -> dict:
    return load_compose()


def test_ut110_services_exist(compose: dict) -> None:
    assert set(compose["services"]) == {"db", "migrate", "api", "scheduler"}


def test_ut110_db_healthcheck_and_no_ports(compose: dict) -> None:
    db = compose["services"]["db"]

    assert db["healthcheck"]["test"] == HEALTHCHECK
    assert db["healthcheck"]["interval"] == "5s"
    assert db["healthcheck"]["timeout"] == "3s"
    assert db["healthcheck"]["retries"] == 12
    assert "ports" not in db
    assert db["volumes"] == ["pgdata:/var/lib/postgresql/data"]
    assert "pgdata" in compose["volumes"]


def test_ut110_startup_ordering(compose: dict) -> None:
    services = compose["services"]

    assert services["migrate"]["depends_on"]["db"]["condition"] == "service_healthy"
    assert services["migrate"]["restart"] == "no"
    for name in ("api", "scheduler"):
        assert services[name]["depends_on"]["migrate"]["condition"] == (
            "service_completed_successfully"
        )


def test_ut110_restart_policy_init_and_grace_period(compose: dict) -> None:
    services = compose["services"]

    assert services["api"]["restart"] == "unless-stopped"
    assert services["scheduler"]["restart"] == "unless-stopped"
    assert services["scheduler"]["init"] is True
    assert services["scheduler"]["stop_grace_period"] == "30s"


def test_ut110_commands_and_published_port(compose: dict) -> None:
    services = compose["services"]

    assert services["migrate"]["command"] == ["alembic", "upgrade", "head"]
    assert services["scheduler"]["command"] == ["take-jobs", "scheduler"]
    assert services["api"]["command"] == [
        "uvicorn",
        "--factory",
        "take_jobs.api.app:create_app",
        "--host",
        "0.0.0.0",
        "--port",
        "8000",
    ]
    assert services["api"]["ports"] == ["${API_PORT-8000}:8000"]


def test_ut110_no_service_uses_env_file(compose: dict) -> None:
    for name, service in compose["services"].items():
        assert "env_file" not in service, name


@pytest.mark.skipif(not DOCKER_AVAILABLE, reason="docker CLI not available")
def test_ut110_renders_without_warnings_and_expands_healthcheck(tmp_path: Path) -> None:
    result = compose_config(tmp_path)

    assert result.returncode == 0, result.stderr
    assert "is not set" not in result.stderr
    assert "warning" not in result.stderr.lower()

    db = json.loads(result.stdout)["services"]["db"]
    healthcheck = " ".join(db["healthcheck"]["test"][1:]).replace("$$", "$")
    # Let the container's shell do the expansion, with `echo` standing in for `pg_isready`.
    probe = healthcheck.replace("pg_isready", "echo")
    expanded = subprocess.run(
        ["sh", "-c", probe],
        capture_output=True,
        text=True,
        env={**clean_environment(), **db["environment"]},
        check=True,
    ).stdout.split()

    assert expanded == ["-U", "take_jobs", "-d", "take_jobs"]
