"""IT-013: SIGTERM and Ctrl+C during a real collection (rule 24, Safety Invariant 8).

Each variant runs the collector in a helper process of its own process group
(`tests.support.collect_helper`), against the real database and a fixture server. Whatever the
outcome, a `finally` kills the helper's whole group, so no helper, crawl child or resource tracker
outlives a test, and a half-finished helper can never hold a database lock into the next test
(the per-test `TRUNCATE` would block on it).
"""

import contextlib
import multiprocessing
import os
import signal
import time
from collections.abc import Callable, Iterator
from dataclasses import replace
from multiprocessing.connection import Connection
from multiprocessing.process import BaseProcess

import pytest

from take_jobs.cli.main import build_cli_deps, main
from take_jobs.config import Settings
from tests.support.cli import FakeScraper
from tests.support.collect_helper import collect_helper
from tests.support.database import fetch
from tests.support.fixture_server import FixtureServer, python_routes

EXIT_BOUND_S = 12.0
STARTUP_TIMEOUT_S = 60.0


def kill_group(pgid: int) -> None:
    with contextlib.suppress(ProcessLookupError, PermissionError):
        os.killpg(pgid, signal.SIGKILL)


def group_is_empty(pgid: int, *, wait_s: float = 5.0) -> bool:
    """True once no process of the group exists (a reaped or reparented zombie is gone)."""
    deadline = time.monotonic() + wait_s
    while True:
        try:
            os.killpg(pgid, 0)
        except ProcessLookupError:
            return True
        except PermissionError:  # the id now belongs to a foreign group: not ours
            return True
        if time.monotonic() >= deadline:
            return False
        time.sleep(0.1)


StartHelper = Callable[[FixtureServer, str], "Helper"]


class Helper:
    def __init__(self, process: BaseProcess, events: Connection) -> None:
        self.process = process
        self.events = events

    @property
    def pid(self) -> int:
        assert self.process.pid is not None
        return self.process.pid

    def wait_for_event(self, name: str, timeout: float = STARTUP_TIMEOUT_S) -> None:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self.events.poll(0.2):
                if self.events.recv() == name:
                    return
            elif not self.process.is_alive():
                pytest.fail(f"the helper exited ({self.process.exitcode}) before {name!r}")
        pytest.fail(f"no {name!r} event within {timeout} s")

    def exit_within(self, limit: float) -> float:
        started = time.monotonic()
        self.process.join(limit + 8)  # a generous join; the assertion below is the real bound
        assert not self.process.is_alive(), "the helper did not exit"
        return time.monotonic() - started


@pytest.fixture
def start_helper(database_url: str) -> Iterator[StartHelper]:
    started: list[Helper] = []
    context = multiprocessing.get_context("spawn")

    def start(server: FixtureServer, variant: str) -> Helper:
        receiver, sender = context.Pipe(duplex=False)
        process = context.Process(
            target=collect_helper, args=(database_url, server.url, variant, sender)
        )
        process.start()
        sender.close()
        helper = Helper(process, receiver)
        started.append(helper)
        helper.wait_for_event("ready")
        return helper

    try:
        yield start
    finally:
        for helper in started:
            kill_group(helper.pid)
            helper.process.join(10)
            helper.events.close()
            if helper.process.exitcode is not None:
                helper.process.close()


def interrupted_run_state(database_url: str) -> tuple[list[tuple], list[tuple]]:
    runs = fetch(database_url, "SELECT id, status, error FROM collection_runs ORDER BY id")
    jobs = fetch(database_url, "SELECT id FROM jobs")
    return runs, jobs


def assert_clean_interruption(database_url: str, helper: Helper, elapsed: float) -> None:
    assert helper.process.exitcode == 4
    assert elapsed < EXIT_BOUND_S
    assert group_is_empty(helper.pid), "a process of the collector's group is still alive"
    runs, jobs = interrupted_run_state(database_url)
    assert runs == [(1, "failed", "interrupted by signal")]
    assert jobs == []  # in the ingestion variant the partial work was rolled back


def collect_is_not_refused(database_url: str) -> None:
    """A following `collect` finds no `running` run: it is not refused with exit 3."""
    deps = replace(
        build_cli_deps(Settings(_env_file=None, database_url=database_url, scrape_terms="python")),
        scraper=FakeScraper(),
    )
    assert main(["collect"], deps=deps) == 0


@pytest.mark.parametrize("how", ["sigterm", "ctrl_c"])
def test_it013_signal_during_the_crawl(
    database_url: str, start_helper: StartHelper, how: str
) -> None:
    """(a) SIGTERM to the collector; (b) SIGINT to its whole process group, as a terminal does."""
    with FixtureServer(python_routes(delay_s=25)) as server:
        helper: Helper = start_helper(server, "crawl")
        assert server.first_listing_hit.wait(STARTUP_TIMEOUT_S), "the crawl never started"

        if how == "sigterm":
            os.kill(helper.pid, signal.SIGTERM)
        else:
            os.killpg(helper.pid, signal.SIGINT)
        elapsed = helper.exit_within(EXIT_BOUND_S)

    assert_clean_interruption(database_url, helper, elapsed)
    collect_is_not_refused(database_url)


def test_it013_sigterm_during_ingestion(database_url: str, start_helper: StartHelper) -> None:
    """(c) The crawl is quick; each upsert then takes 2 s. SIGTERM lands during the first one."""
    with FixtureServer(python_routes()) as server:
        helper: Helper = start_helper(server, "ingest")
        helper.wait_for_event("upsert_started")

        os.kill(helper.pid, signal.SIGTERM)
        elapsed = helper.exit_within(EXIT_BOUND_S)

    assert_clean_interruption(database_url, helper, elapsed)
    collect_is_not_refused(database_url)
