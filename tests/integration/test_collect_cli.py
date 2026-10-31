"""The collector against a real PostgreSQL (IT-007, IT-009).

These tests call `main()` or run whole collect cycles, which use `asyncio.run` and install signal
handlers, so they are synchronous (the session event loop of the async fixtures is not running
while a synchronous test body executes). Database state is read through `tests.support.database`,
which opens its own short-lived engine.
"""

import asyncio
import json
from collections.abc import Iterator
from dataclasses import replace

import pytest

from take_jobs.cli.main import CliDeps, build_cli_deps, main
from take_jobs.config import Settings
from take_jobs.domain.models import CollectionRun, RunStatus, RunTrigger, ScrapeReport
from take_jobs.infrastructure.scraping.registry import SOURCES, with_base_url
from tests.support.cli import FakeScraper, two_outcome_report
from tests.support.database import execute, fetch
from tests.support.fixture_server import FixtureServer, python_routes
from tests.support.socket_guard import install_test_socket_guard


@pytest.fixture
def server() -> Iterator[FixtureServer]:
    with FixtureServer(python_routes()) as running:
        yield running


def make_deps(database_url: str, **settings: object) -> CliDeps:
    return build_cli_deps(
        Settings(_env_file=None, database_url=database_url, scrape_terms="python", **settings)  # type: ignore[arg-type]
    )


def real_crawl_deps(database_url: str, server: FixtureServer) -> CliDeps:
    settings = Settings(_env_file=None, database_url=database_url, scrape_terms="python")
    return build_cli_deps(
        settings,
        with_base_url(SOURCES, server.url),
        child_initializer=install_test_socket_guard,
    )


def run_rows(database_url: str) -> list[tuple]:
    return fetch(database_url, "SELECT id, status, error, trigger FROM collection_runs ORDER BY id")


def test_it007_two_full_cycles_in_one_process(database_url: str, server: FixtureServer) -> None:
    """start_run -> scrape -> complete_run, twice in this process: no `ReactorNotRestartable`,
    no pickling error (risks R1 and R6)."""
    deps = real_crawl_deps(database_url, server)

    async def start() -> int:
        async with deps.open_collection_service() as service:
            return await service.start_run(RunTrigger.MANUAL, expected_combinations=2)

    async def complete(run_id: int, report: ScrapeReport) -> CollectionRun:
        async with deps.open_collection_service() as service:
            return await service.complete_run(run_id, report)

    runs = []
    for _ in range(2):
        run_id = asyncio.run(start())
        report = deps.scraper.scrape(["python"])

        assert [(o.source, o.term) for o in report.outcomes] == [
            ("vagas", "python"),
            ("infojobs", "python"),
        ]
        by_source = {o.source: o for o in report.outcomes}
        assert by_source["vagas"].pages == 2
        # The walk goes past page 2: pages 1-3 bring 20 unseen jobs each, page 4 ends the list.
        assert by_source["infojobs"].pages == 4
        assert len(by_source["infojobs"].jobs) == 60
        assert all(o.error is None for o in report.outcomes)
        runs.append(asyncio.run(complete(run_id, report)))

    first, second = runs
    assert (first.status, second.status) == (RunStatus.SUCCESS, RunStatus.SUCCESS)
    assert first.totals.new > 0
    assert second.totals.new == 0  # the second cycle sees the same listings again
    assert second.totals.seen_again == first.totals.new + first.totals.seen_again
    sources = fetch(database_url, "SELECT DISTINCT source FROM jobs ORDER BY source")
    assert sources == [("infojobs",), ("vagas",)]
    statuses = [status for _, status, _, _ in run_rows(database_url)]
    assert statuses == ["success", "success"]


def test_it007_two_collect_commands_in_one_process(
    database_url: str, server: FixtureServer, capsys: pytest.CaptureFixture[str]
) -> None:
    """The same, through the command: two `main(["collect", "--json"])` with the real crawl."""
    deps = real_crawl_deps(database_url, server)

    codes = [main(["collect", "--json"], deps=deps) for _ in range(2)]

    documents = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    assert codes == [0, 0]
    assert [d["status"] for d in documents] == ["success", "success"]
    assert [len(d["results"]) for d in documents] == [2, 2]
    assert documents[0]["totals"]["new"] > 0
    assert documents[1]["totals"]["new"] == 0


def test_it009_a_live_run_is_refused_with_exit_3(
    database_url: str, capsys: pytest.CaptureFixture[str]
) -> None:
    execute(
        database_url,
        "INSERT INTO collection_runs (trigger, status, started_at, expected_combinations) "
        "VALUES ('manual', 'running', now() - interval '5 minutes', 24)",
    )
    scraper = FakeScraper()
    deps = replace(make_deps(database_url), scraper=scraper)

    code = main(["collect"], deps=deps)

    assert code == 3
    assert capsys.readouterr().err.startswith("Another collection run (id 1) is in progress since ")
    assert scraper.scrape_calls == []
    assert run_rows(database_url) == [(1, "running", None, "manual")]


def test_it009_a_stale_run_is_taken_over_and_the_new_run_finishes(
    database_url: str, capsys: pytest.CaptureFixture[str]
) -> None:
    execute(
        database_url,
        "INSERT INTO collection_runs (trigger, status, started_at, expected_combinations) "
        "VALUES ('scheduled', 'running', now() - :age * interval '1 minute', 24)",
        age=61,
    )
    scraper = FakeScraper(report=two_outcome_report())
    deps = replace(make_deps(database_url), scraper=scraper)
    assert deps.settings.scrape_run_timeout_minutes == 60

    code = main(["collect"], deps=deps)

    assert code == 0
    assert run_rows(database_url) == [
        (1, "failed", "interrupted", "scheduled"),
        (2, "success", None, "manual"),
    ]
    assert "finished: success" in capsys.readouterr().out
