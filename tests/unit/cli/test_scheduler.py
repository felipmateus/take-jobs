"""The `take-jobs scheduler` seams (UT-080 to UT-088). No case blocks and none starts a real loop.

The scheduler object is an APScheduler `BackgroundScheduler` that is never started (its `start`
only records an event), the runner records its calls, `sleep` records the backoff delays and the
store is the in-memory fake. `signal.signal` is replaced wherever a case runs `run_scheduler`.
"""

import logging
import signal
import subprocess
import sys
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import timedelta
from types import FrameType
from typing import Any

import pytest
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from sqlalchemy.exc import OperationalError

from take_jobs.application.services import CollectionService
from take_jobs.cli.main import CliDeps, main
from take_jobs.cli.scheduler import (
    DatabaseUnavailableError,
    configure_scheduler,
    make_shutdown_handler,
    run_scheduler,
    run_startup,
    wait_for_database,
)
from take_jobs.config import Settings
from take_jobs.domain.models import RunStatus, RunTrigger
from take_jobs.domain.rules import RelevancePolicy
from take_jobs.infrastructure.scraping.registry import SOURCES
from tests.fakes import NOW, FixedClock, InMemoryStore, InMemoryUnitOfWork
from tests.support.cli import job

SCHEDULER_LOGGER = "take_jobs.cli.scheduler"


class RecordingRunner:
    def __init__(self, events: list[str]) -> None:
        self.events = events
        self.calls: list[RunTrigger] = []
        self.terminated: list[float] = []
        self.on_run: Callable[[], None] | None = None

    def run(self, trigger: RunTrigger) -> int:
        self.events.append(f"run:{trigger.value}")
        self.calls.append(trigger)
        if self.on_run is not None:
            self.on_run()
        return 0

    def terminate_current(self, wait_s: float) -> None:
        self.events.append("terminate")
        self.terminated.append(wait_s)


class NeverStartedScheduler(BackgroundScheduler):
    """A real APScheduler whose loop is never started: `start` only records the event."""

    def __init__(self, events: list[str], **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.events = events

    def start(self, paused: bool = False) -> None:
        self.events.append("scheduler_start")


@dataclass
class Rig:
    store: InMemoryStore = field(default_factory=InMemoryStore)
    clock: FixedClock = field(default_factory=FixedClock)
    events: list[str] = field(default_factory=list)
    sleeps: list[float] = field(default_factory=list)
    opens: int = 0

    def __post_init__(self) -> None:
        self.runner = RecordingRunner(self.events)
        self.scheduler: NeverStartedScheduler | None = None

    def deps(self, **env: str) -> CliDeps:
        settings = Settings(_env_file=None, scrape_terms="python", **env)  # type: ignore[arg-type]
        relevance = RelevancePolicy(
            settings.relevance_include_keywords, settings.relevance_exclude_keywords
        )

        @asynccontextmanager
        async def open_collection_service() -> AsyncIterator[CollectionService]:
            self.opens += 1
            self.events.append("probe")
            yield CollectionService(
                lambda: InMemoryUnitOfWork(self.store),
                relevance,
                self.clock,
                timedelta(minutes=60),
            )

        def factory() -> NeverStartedScheduler:
            self.scheduler = NeverStartedScheduler(self.events, timezone=settings.scrape_timezone)
            return self.scheduler

        return CliDeps(
            settings=settings,
            sources=SOURCES,
            relevance=relevance,
            scraper=None,  # type: ignore[arg-type]  # collector only
            open_collection_service=open_collection_service,
            clock=self.clock,
            runner=self.runner,
            sleep=self.sleeps.append,
            scheduler_factory=factory,
        )

    def seed_jobs(self) -> None:
        self.store.add_job(job("1", "Desenvolvedor Python"), seen_at=NOW - timedelta(days=1))

    def seed_finished_run(self, hours_ago: float, status: RunStatus = RunStatus.SUCCESS) -> None:
        self.store.add_run(started_at=NOW - timedelta(hours=hours_ago), status=status)


@pytest.fixture
def rig() -> Rig:
    return Rig()


@pytest.fixture
def installed_signals(monkeypatch: pytest.MonkeyPatch) -> dict[int, Any]:
    """Replace `signal.signal` with a recorder that returns the previous handler."""
    installed: dict[int, Any] = {}

    def fake_signal(signum: int, handler: Any) -> Any:
        previous = installed.get(signum, signal.SIG_DFL)
        installed[signum] = handler
        return previous

    monkeypatch.setattr(signal, "signal", fake_signal)
    return installed


# --- UT-080 to UT-082: rule 14 at start-up -------------------------------------------------------


@pytest.mark.parametrize(
    ("seed", "reason"),
    [
        pytest.param(lambda rig: None, "empty_job_store", id="empty-store"),
        pytest.param(
            lambda rig: (rig.seed_jobs(), rig.seed_finished_run(25)),
            "no_recent_run",
            id="latest-run-25h-ago",
        ),
        pytest.param(
            lambda rig: (rig.seed_jobs(), rig.seed_finished_run(5, RunStatus.FAILED)),
            None,
            id="failed-run-5h-ago-counts-as-finished",
        ),
    ],
)
def test_run_startup_applies_rule_14(
    rig: Rig,
    seed: Callable[[Rig], object],
    reason: str | None,
    caplog: pytest.LogCaptureFixture,
) -> None:
    seed(rig)
    with caplog.at_level(logging.INFO, logger=SCHEDULER_LOGGER):
        result = run_startup(rig.deps())

    assert result == reason
    if reason is None:
        assert rig.runner.calls == []
    else:
        assert rig.runner.calls == [RunTrigger.STARTUP]
        assert f"event=startup_collection reason={reason}" in caplog.text


def test_run_scheduler_runs_the_startup_collection_before_the_loop_starts(
    rig: Rig, installed_signals: dict[int, Any]
) -> None:
    code = run_scheduler(rig.deps())

    assert code == 0
    assert rig.runner.calls == [RunTrigger.STARTUP]
    assert rig.events.index("run:startup") < rig.events.index("scheduler_start")


def test_run_startup_skips_a_recent_run_and_logs_it(
    rig: Rig, caplog: pytest.LogCaptureFixture
) -> None:
    rig.seed_jobs()
    rig.seed_finished_run(3)

    with caplog.at_level(logging.INFO, logger=SCHEDULER_LOGGER):
        result = run_startup(rig.deps())

    assert result is None
    assert rig.runner.calls == []
    assert "event=startup_collection_skipped reason=recent_run_exists" in caplog.text


def test_run_startup_is_disabled_by_the_flag(rig: Rig, caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.INFO, logger=SCHEDULER_LOGGER):
        result = run_startup(rig.deps(SCRAPE_ON_START="false"))

    assert result is None
    assert rig.runner.calls == []
    assert rig.opens == 0  # the database is not even asked
    assert "event=startup_collection_skipped reason=disabled" in caplog.text


# --- UT-083: the cron job ------------------------------------------------------------------------


def _fields(trigger: CronTrigger) -> dict[str, str]:
    return {field.name: str(field) for field in trigger.fields}


@pytest.mark.parametrize(
    ("cron", "expected"),
    [
        ("0 6 * * *", {"hour": "6", "minute": "0", "day_of_week": "*"}),
        ("30 22 * * *", {"hour": "22", "minute": "30", "day_of_week": "*"}),
        ("0 6 * * 0", {"hour": "6", "minute": "0", "day_of_week": "sun"}),
    ],
)
def test_configure_scheduler_adds_the_only_cron_job(
    rig: Rig, cron: str, expected: dict[str, str]
) -> None:
    deps = rig.deps(SCRAPE_CRON=cron)
    scheduler = deps.scheduler_factory()

    configure_scheduler(scheduler, deps)

    (scheduled,) = scheduler.get_jobs()
    assert isinstance(scheduled.trigger, CronTrigger)
    assert expected.items() <= _fields(scheduled.trigger).items()
    assert str(scheduled.trigger.timezone) == "America/Sao_Paulo"
    assert scheduled.max_instances == 1
    assert scheduled.coalesce is True
    assert scheduled.misfire_grace_time == 3600
    assert not scheduler.running
    scheduled.func(*scheduled.args, **scheduled.kwargs)
    assert rig.runner.calls == [RunTrigger.SCHEDULED]


def test_configure_scheduler_uses_the_configured_timezone(rig: Rig) -> None:
    deps = rig.deps(SCRAPE_TIMEZONE="Europe/Lisbon")
    scheduler = deps.scheduler_factory()

    configure_scheduler(scheduler, deps)

    assert str(scheduler.get_jobs()[0].trigger.timezone) == "Europe/Lisbon"


# --- UT-085: waiting for the database ------------------------------------------------------------


class FlakyPing:
    """`open_service` whose `ping()` fails `failures` times (forever when `None`)."""

    def __init__(self, failures: int | None) -> None:
        self.failures = failures
        self.attempts = 0

    def __call__(self) -> Any:
        @asynccontextmanager
        async def open_service() -> AsyncIterator[Any]:
            self.attempts += 1

            class Service:
                async def ping(inner) -> None:
                    if self.failures is None or self.attempts <= self.failures:
                        raise OperationalError("SELECT 1", {}, ConnectionRefusedError("refused"))

            yield Service()

        return open_service()


def test_wait_for_database_backs_off_1_2_4_then_returns(caplog: pytest.LogCaptureFixture) -> None:
    sleeps: list[float] = []
    ping = FlakyPing(failures=3)

    with caplog.at_level(logging.WARNING, logger=SCHEDULER_LOGGER):
        wait_for_database(ping, sleep=sleeps.append)  # type: ignore[arg-type]

    assert sleeps == [1, 2, 4]
    assert ping.attempts == 4
    assert caplog.text.count("event=startup_probe_failed") == 3


def test_wait_for_database_gives_up_after_the_maximum_wait(
    caplog: pytest.LogCaptureFixture,
) -> None:
    sleeps: list[float] = []

    with (
        caplog.at_level(logging.WARNING, logger=SCHEDULER_LOGGER),
        pytest.raises(DatabaseUnavailableError),
    ):
        wait_for_database(FlakyPing(failures=None), sleep=sleeps.append)  # type: ignore[arg-type]

    assert sleeps[:6] == [1, 2, 4, 8, 10, 10]
    assert set(sleeps[5:]) == {10}
    assert sum(sleeps) >= 60
    assert sum(sleeps[:-1]) < 60  # it stops at the first attempt after the budget is spent
    assert caplog.text.count("event=startup_probe_failed") == len(sleeps) + 1


def test_wait_for_database_honors_a_smaller_budget() -> None:
    sleeps: list[float] = []

    with pytest.raises(DatabaseUnavailableError):
        wait_for_database(FlakyPing(failures=None), sleep=sleeps.append, max_wait_s=5)  # type: ignore[arg-type]

    assert sleeps == [1, 2, 4]


def test_run_scheduler_returns_1_when_the_database_never_answers(
    rig: Rig, installed_signals: dict[int, Any], caplog: pytest.LogCaptureFixture
) -> None:
    rig.store.ping_error = OperationalError("SELECT 1", {}, ConnectionRefusedError("refused"))

    with caplog.at_level(logging.INFO, logger=SCHEDULER_LOGGER):
        code = run_scheduler(rig.deps())

    assert code == 1
    assert sum(rig.sleeps) >= 60
    assert rig.runner.calls == []
    assert "scheduler_start" not in rig.events
    assert rig.scheduler is not None
    assert rig.scheduler.get_jobs() == []
    assert "event=scheduler_failed reason=database_unavailable" in caplog.text


# --- UT-086: the command line --------------------------------------------------------------------


def test_the_module_entry_point_lists_both_commands() -> None:
    result = subprocess.run(
        [sys.executable, "-m", "take_jobs", "--help"],
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )

    assert result.returncode == 0
    assert "collect" in result.stdout
    assert "scheduler" in result.stdout


def test_main_dispatches_the_scheduler_command(rig: Rig, installed_signals: dict[int, Any]) -> None:
    assert main(["scheduler"], deps=rig.deps()) == 0
    assert rig.events[-1] == "scheduler_start"


def test_main_reports_invalid_cron_without_starting(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("SCRAPE_CRON", "not a cron")

    assert main(["scheduler"]) == 2
    assert "Invalid configuration: SCRAPE_CRON" in capsys.readouterr().err


# --- UT-087: the shutdown handler ----------------------------------------------------------------


class StubScheduler:
    def __init__(self, *, running: bool, events: list[str]) -> None:
        self.running = running
        self.events = events

    def shutdown(self, wait: bool = True) -> None:
        self.events.append(f"shutdown(wait={wait})")


@pytest.mark.parametrize(
    ("running", "expected"),
    [(True, ["shutdown(wait=False)", "terminate"]), (False, ["terminate"])],
    ids=["scheduler-running", "scheduler-not-started"],
)
def test_the_shutdown_handler_stops_the_loop_forwards_the_signal_and_exits_0(
    running: bool, expected: list[str]
) -> None:
    events: list[str] = []
    runner = RecordingRunner(events)
    handler = make_shutdown_handler(StubScheduler(running=running, events=events), runner)  # type: ignore[arg-type]

    with pytest.raises(SystemExit) as stop:
        handler(signal.SIGTERM, None)

    assert stop.value.code == 0
    assert events == expected
    assert runner.terminated == [25]


def test_the_shutdown_handler_passes_the_wait_through() -> None:
    runner = RecordingRunner([])
    handler = make_shutdown_handler(StubScheduler(running=False, events=[]), runner, wait_s=7)  # type: ignore[arg-type]

    with pytest.raises(SystemExit):
        handler(signal.SIGINT, None)

    assert runner.terminated == [7]


# --- UT-088: the handler is installed first ------------------------------------------------------


def test_run_scheduler_installs_the_handler_before_the_probe_and_the_startup_run(
    rig: Rig, installed_signals: dict[int, Any], caplog: pytest.LogCaptureFixture
) -> None:
    original = {
        signal.SIGTERM: signal.SIG_DFL,
        signal.SIGINT: signal.SIG_DFL,
    }
    installs: list[int] = []
    real_fake = signal.signal

    def recording_signal(signum: int, handler: Any) -> Any:
        if handler not in original.values():
            installs.append(signum)
            rig.events.append(f"install:{signal.Signals(signum).name}")
        return real_fake(signum, handler)

    def stop_during_startup_run() -> None:
        handler = installed_signals[signal.SIGTERM]
        frame: FrameType | None = None
        handler(signal.SIGTERM, frame)

    rig.runner.on_run = stop_during_startup_run
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(signal, "signal", recording_signal)
        with (
            caplog.at_level(logging.INFO, logger=SCHEDULER_LOGGER),
            pytest.raises(SystemExit) as stop,
        ):
            run_scheduler(rig.deps())

    assert stop.value.code == 0
    assert set(installs) == {signal.SIGTERM, signal.SIGINT}
    order = rig.events
    assert max(order.index("install:SIGTERM"), order.index("install:SIGINT")) < order.index("probe")
    assert order.index("probe") < order.index("run:startup")
    assert rig.runner.terminated == [25]
    assert "scheduler_start" not in order  # the stop ended the process during the startup run
    assert caplog.text.index("event=scheduler_started") < caplog.text.index(
        "event=startup_collection"
    )
    # the original handlers are back
    assert installed_signals[signal.SIGTERM] is signal.SIG_DFL
    assert installed_signals[signal.SIGINT] is signal.SIG_DFL


def test_scheduler_started_logs_the_next_fire_time(
    rig: Rig, installed_signals: dict[int, Any], caplog: pytest.LogCaptureFixture
) -> None:
    rig.seed_jobs()
    rig.seed_finished_run(1)

    with caplog.at_level(logging.INFO, logger=SCHEDULER_LOGGER):
        run_scheduler(rig.deps())

    # NOW is 2026-10-30 12:00Z = 09:00 in Sao Paulo, so the next 06:00 is the next day.
    assert "event=scheduler_started" in caplog.text
    assert "next_run=2026-10-31T06:00:00-03:00" in caplog.text
