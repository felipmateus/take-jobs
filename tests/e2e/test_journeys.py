"""E2E-001 to E2E-004: `take-jobs collect`, then the HTTP API, on a real database.

Every test is synchronous: `main()` runs its own event loops and installs signal handlers, and
`TestClient` runs the application on its own loop. The sites are the fixture server.
"""

import time
from collections.abc import Iterator
from typing import Any

import pytest

from take_jobs.api.schemas import RunDetailOut
from tests.support.database import execute, fetch
from tests.support.fixture_server import FixtureServer, Route, journey_routes, python_routes
from tests.support.journey import Journey, json_of

JOB_FIELDS = {
    "id",
    "title",
    "company",
    "location",
    "description",
    "published_label",
    "source",
    "url",
    "seniority",
    "first_seen_at",
    "last_seen_at",
    "active",
}


@pytest.fixture
def python_journey(database_url: str) -> Iterator[Journey]:
    with FixtureServer(python_routes()) as server:
        yield Journey(database_url, server, terms="python")


@pytest.fixture
def desenvolvedor_programador(database_url: str) -> Iterator[Journey]:
    with FixtureServer(journey_routes()) as server:
        yield Journey(database_url, server, terms="desenvolvedor,programador")


def results_by_key(run: dict[str, Any]) -> dict[tuple[str, str], dict[str, Any]]:
    return {(r["source"], r["term"]): r for r in run["results"]}


def test_e2e001_collect_then_search_detail_and_history(
    python_journey: Journey, capsys: pytest.CaptureFixture[str]
) -> None:
    collected = python_journey.collect(capsys, "--json")

    assert collected.exit_code == 0
    cli = collected.run()
    assert cli.status == "success"
    assert len(cli.results) == 2

    with python_journey.api() as client:
        found = client.get("/jobs?q=python")
        assert found.status_code == 200
        page = found.json()
        assert page["total"] > 0
        assert page["items"]
        for item in page["items"]:
            assert set(item) == JOB_FIELDS
            assert item["active"] is True
        assert any(item["seniority"] is not None for item in page["items"])

        first = page["items"][0]
        detail = client.get(f"/jobs/{first['id']}")
        assert detail.status_code == 200
        assert detail.json() == first

        runs = client.get("/collection-runs")
        assert runs.status_code == 200
        listing = runs.json()
        assert listing["total"] == 1
        assert len(listing["items"]) == 1
        assert listing["items"][0]["totals"] == cli.totals.model_dump()

        run_detail = client.get(f"/collection-runs/{cli.id}")
        assert run_detail.status_code == 200
        assert run_detail.json()["results"] == json_of(collected)["results"]
        assert RunDetailOut.model_validate(run_detail.json()) == cli


def test_e2e002_relevance_and_deduplication(
    desenvolvedor_programador: Journey, capsys: pytest.CaptureFixture[str]
) -> None:
    journey = desenvolvedor_programador
    collected = journey.collect(capsys, "--json")
    assert collected.exit_code == 0
    run = json_of(collected)

    with journey.api() as client:
        assert client.get("/jobs?q=cnc").json()["total"] == 0
        java = client.get("/jobs?q=backend java").json()
        assert java["total"] == 1
        job = java["items"][0]
        assert job["title"] == "Desenvolvedor Backend Java"

        results = results_by_key(client.get(f"/collection-runs/{run['id']}").json())
        assert results[("vagas", "programador")]["discarded"] == 1
        assert results[("vagas", "programador")]["seen_again"] == 1
        assert results[("vagas", "desenvolvedor")]["seen_again"] == 0

        time.sleep(1.1)  # the second run must stamp a visibly newer last_seen_at
        assert journey.collect(capsys).exit_code == 0

        again = client.get(f"/jobs/{job['id']}").json()
        assert again["first_seen_at"] == job["first_seen_at"]
        assert again["last_seen_at"] > job["last_seen_at"]
        assert client.get("/jobs?q=backend java").json()["total"] == 1
        assert client.get("/collection-runs").json()["total"] == 2


def test_e2e003_lifecycle_and_reactivation(
    desenvolvedor_programador: Journey, capsys: pytest.CaptureFixture[str]
) -> None:
    journey = desenvolvedor_programador
    assert journey.collect(capsys).exit_code == 0

    with journey.api() as client:
        everything = client.get("/jobs?size=100").json()
        assert everything["total"] >= 2
        target = everything["items"][0]
        execute(
            journey.database_url,
            "UPDATE jobs SET first_seen_at = now() - interval '9 days', "
            "last_seen_at = now() - interval '8 days' WHERE id = :id",
            id=target["id"],
        )

        active_ids = [i["id"] for i in client.get("/jobs?size=100").json()["items"]]
        assert target["id"] not in active_ids

        with_inactive = client.get("/jobs?include_inactive=true&size=100").json()
        stale = next(i for i in with_inactive["items"] if i["id"] == target["id"])
        assert stale["active"] is False
        assert client.get(f"/jobs/{target['id']}").json()["active"] is False

        assert journey.collect(capsys).exit_code == 0

        revived = [
            i for i in client.get("/jobs?size=100").json()["items"] if i["id"] == target["id"]
        ]
        assert [i["active"] for i in revived] == [True]
        assert fetch(
            journey.database_url,
            "SELECT first_seen_at < now() - interval '8 days' FROM jobs WHERE id = :id",
            id=target["id"],
        ) == [(True,)]


def test_e2e004_one_source_failing_leaves_a_partial_run(
    database_url: str, capsys: pytest.CaptureFixture[str]
) -> None:
    forbidden = Route(body=b"forbidden", status=403)
    routes = {
        **python_routes(),
        "/vagas-de-emprego-python.aspx?page=1": forbidden,
    }
    with FixtureServer(routes) as server:
        journey = Journey(database_url, server, terms="python")
        collected = journey.collect(capsys)

        assert collected.exit_code == 0
        summary = collected.stdout.strip().splitlines()[-1]
        assert " finished: partial in " in summary

        with journey.api() as client:
            run_id = client.get("/collection-runs").json()["items"][0]["id"]
            results = results_by_key(client.get(f"/collection-runs/{run_id}").json())
            assert results[("infojobs", "python")]["status"] == "failed"
            assert results[("infojobs", "python")]["error"] == "HTTP 403 Forbidden"
            assert results[("vagas", "python")]["status"] == "success"
            assert client.get("/jobs?source=vagas").json()["total"] > 0
            assert client.get("/jobs?source=infojobs").json()["total"] == 0
