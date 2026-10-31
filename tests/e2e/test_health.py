"""E2E-005: `GET /health` with and without a database, plus the API's behavior on a dead one."""

import socket
import time

from fastapi.testclient import TestClient

from take_jobs.api.app import create_app
from take_jobs.config import Settings


def closed_port_url() -> str:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    return f"postgresql+asyncpg://u:take_jobs_dev@127.0.0.1:{port}/db"


def test_e2e005_health_with_the_database(database_url: str) -> None:
    app = create_app(Settings(_env_file=None, database_url=database_url))

    with TestClient(app) as client:
        response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "database": "ok"}


def test_e2e005_health_without_the_database() -> None:
    app = create_app(Settings(_env_file=None, database_url=closed_port_url()))

    with TestClient(app) as client:
        started = time.monotonic()
        response = client.get("/health")
        elapsed = time.monotonic() - started

    assert response.status_code == 503
    assert response.json() == {"status": "unavailable", "database": "unreachable"}
    assert elapsed < 3.5


def test_every_database_backed_route_answers_503_when_the_database_is_down() -> None:
    app = create_app(Settings(_env_file=None, database_url=closed_port_url()))
    expected = {
        "error": {
            "code": "database_unavailable",
            "message": "The database is unavailable. Try again later.",
            "details": [],
        }
    }

    with TestClient(app, raise_server_exceptions=False) as client:
        for path in ("/jobs", "/jobs/1", "/collection-runs", "/collection-runs/1"):
            response = client.get(path)
            assert response.status_code == 503, path
            assert response.json() == expected, path
