"""`take-jobs collect` through `main(argv, deps=...)` with in-memory fakes (UT-070 to UT-079,
UT-104, UT-105, UT-117).

Signals are delivered by calling the installed handler directly, never with `os.kill`, so these
tests cannot disturb the test process. `main` must run in the main thread (it installs signal
handlers and calls `asyncio.run`), so every test here is synchronous.
"""

import asyncio
import json
import logging
import signal
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from pydantic import BaseModel, ConfigDict
from sqlalchemy.exc import IntegrityError, OperationalError

from take_jobs.api.schemas import RunDetailOut
from take_jobs.application.services import CollectionService
from take_jobs.cli.main import CliDeps, build_cli_deps, main
from take_jobs.config import Settings
from take_jobs.domain.errors import (
    RunAlreadyActiveError,
    RunTakenOverError,
    ScrapeCrashedError,
    ScrapeInterruptedError,
)
from take_jobs.domain.models import CollectionRun, RunStatus, RunTrigger, ScrapeReport
from take_jobs.domain.rules import RelevancePolicy
from take_jobs.infrastructure.scraping.registry import SOURCES
from tests.fakes import NOW, FixedClock, InMemoryStore, InMemoryUnitOfWork
from tests.support.cli import FakeScraper, outcome, two_outcome_report

Override = Callable[..., Awaitable[Any]]


class ScriptedService(CollectionService):
    """The real `CollectionService` over in-memory fakes, with per-method scripted behavior.

    An override is `async def override(real, *args, **kwargs)`; `real` is the real method.
    Every call is recorded in `calls` as `(name, *arguments)`.
    """

    def __init__(
        self,
        *args: Any,
        overrides: dict[str, Override],
        calls: list[tuple[Any, ...]],
        **kwargs: Any,
    ) -> None:
        super().__init__(*args, **kwargs)
        self._overrides = overrides
        self.calls = calls

    async def _run(self, name: str, real: Override, *args: Any, **kwargs: Any) -> Any:
        if name in self._overrides:
            return await self._overrides[name](real, *args, **kwargs)
        return await real(*args, **kwargs)

    async def start_run(self, trigger: RunTrigger, expected_combinations: int) -> int:
        self.calls.append(("start_run", trigger, expected_combinations))
        return await self._run("start_run", super().start_run, trigger, expected_combinations)

    async def complete_run(
        self,
        run_id: int,
        report: ScrapeReport,
        *,
        before_commit: Callable[[], None] | None = None,
    ) -> CollectionRun:
        self.calls.append(("complete_run", run_id, before_commit))
        return await self._run(
            "complete_run", super().complete_run, run_id, report, before_commit=before_commit
        )

    async def get_run(self, run_id: int) -> CollectionRun | None:
        self.calls.append(("get_run", run_id))
        return await self._run("get_run", super().get_run, run_id)

    async def fail_run(self, run_id: int, error: str) -> CollectionRun:
        self.calls.append(("fail_run", run_id, error))
        return await self._run("fail_run", super().fail_run, run_id, error)


@dataclass
class Rig:
    store: InMemoryStore = field(default_factory=InMemoryStore)
    clock: FixedClock = field(default_factory=FixedClock)
    scraper: FakeScraper = field(default_factory=FakeScraper)
    overrides: dict[str, Override] = field(default_factory=dict)
    calls: list[tuple[Any, ...]] = field(default_factory=list)
    opens: int = 0

    def names(self) -> list[str]:
        return [call[0] for call in self.calls]

    def fail_run_messages(self) -> list[str]:
        return [call[2] for call in self.calls if call[0] == "fail_run"]

    def deps(self, settings: Settings | None = None) -> CliDeps:
        settings = settings or Settings(_env_file=None, scrape_terms="python")
        relevance = RelevancePolicy(
            settings.relevance_include_keywords, settings.relevance_exclude_keywords
        )

        @asynccontextmanager
        async def open_collection_service() -> AsyncIterator[CollectionService]:
            self.opens += 1
            yield ScriptedService(
                lambda: InMemoryUnitOfWork(self.store),
                relevance,
                self.clock,
                timedelta(minutes=60),
                overrides=self.overrides,
                calls=self.calls,
            )

        return CliDeps(
            settings=settings,
            sources=SOURCES,
            relevance=relevance,
            scraper=self.scraper,
            open_collection_service=open_collection_service,
            clock=self.clock,
            runner=None,  # type: ignore[arg-type]  # scheduler only
            sleep=lambda _: None,
            scheduler_factory=lambda: None,  # type: ignore[arg-type,return-value]
        )

    def run(self, *argv: str) -> int:
        return main(list(argv) or ["collect"], deps=self.deps())


@pytest.fixture
def rig() -> Rig:
    return Rig()


@pytest.fixture(autouse=True)
def handlers_are_restored() -> Any:
    before = {sig: signal.getsignal(sig) for sig in (signal.SIGTERM, signal.SIGINT)}
    yield
    after = {sig: signal.getsignal(sig) for sig in (signal.SIGTERM, signal.SIGINT)}
    assert after == before, "the collector left its signal handler installed"


class RunDetailShape(BaseModel):
    """The `GET /collection-runs/{id}` document of `_dx.md`; extra keys are an error."""

    model_config = ConfigDict(extra="forbid", strict=True)

    class Totals(BaseModel):
        model_config = ConfigDict(extra="forbid", strict=True)
        new: int
        seen_again: int
        discarded: int

    class Result(BaseModel):
        model_config = ConfigDict(extra="forbid", strict=True)
        source: str
        term: str
        status: str
        pages: int
        new: int
        seen_again: int
        discarded: int
        error: str | None

    id: int
    trigger: str
    status: str
    started_at: datetime
    finished_at: datetime | None
    error: str | None
    totals: Totals
    results: list[Result]


def handler_for(sig: int = signal.SIGTERM) -> Callable[[int, Any], None]:
    handler = signal.getsignal(sig)
    assert callable(handler)
    return handler


# -- UT-070 to UT-079 ---------------------------------------------------------------------


def test_ut070_happy_path_prints_started_one_line_per_outcome_and_summary(
    rig: Rig, capsys: pytest.CaptureFixture[str]
) -> None:
    rig.scraper.report = ScrapeReport(
        outcomes=(
            outcome("vagas", "python", [], pages=3),
            outcome("infojobs", "python", [], pages=1),
        )
    )

    code = rig.run("collect")

    out, err = capsys.readouterr()
    lines = out.splitlines()
    assert code == 0
    assert lines[0] == "Collection run 1 started (trigger: manual)"
    assert len(lines) == 4
    assert lines[1].startswith("vagas")
    assert "ok" in lines[1]
    assert "pages=3" in lines[1]
    assert lines[2].startswith("infojobs")
    assert "ok" in lines[2]
    assert lines[3].startswith("Collection run 1 finished: success in ")
    assert lines[3].endswith("(new=0, seen_again=0, discarded=0)")
    assert err == ""


def test_ut070_result_lines_follow_the_documented_columns(
    rig: Rig, capsys: pytest.CaptureFixture[str]
) -> None:
    rig.scraper.report = ScrapeReport(
        outcomes=(
            outcome("vagas", "python", [], pages=20),
            outcome("infojobs", "python", [], pages=0, error="HTTP 403 Forbidden"),
        )
    )

    assert rig.run("collect") == 0  # one combination succeeded: partial

    lines = capsys.readouterr().out.splitlines()
    assert lines[1] == "vagas     python  ok      pages=20  new=0    seen_again=0    discarded=0"
    assert lines[2] == (
        "infojobs  python  FAILED  pages=0   new=0    seen_again=0    discarded=0    "
        'error="HTTP 403 Forbidden"'
    )
    assert lines[3].startswith("Collection run 1 finished: partial in ")


@pytest.mark.parametrize(
    ("errors", "status", "expected_code"),
    [
        ((None, "HTTP 403 Forbidden"), "partial", 0),
        (("HTTP 403 Forbidden", "HTTP 403 Forbidden"), "failed", 1),
        ((None, None), "success", 0),
    ],
)
def test_ut071_exit_code_follows_the_final_status(
    rig: Rig,
    capsys: pytest.CaptureFixture[str],
    errors: tuple[str | None, str | None],
    status: str,
    expected_code: int,
) -> None:
    rig.scraper.report = ScrapeReport(
        outcomes=(
            outcome("vagas", "python", error=errors[0]),
            outcome("infojobs", "python", error=errors[1]),
        )
    )

    assert rig.run("collect") == expected_code

    assert f"finished: {status} in " in capsys.readouterr().out


def test_ut072_run_already_active_exits_3_without_crawling(
    rig: Rig, capsys: pytest.CaptureFixture[str]
) -> None:
    async def refuse(real: Override, *_: Any) -> int:
        raise RunAlreadyActiveError(7, datetime(2026, 10, 30, 9, 0, tzinfo=UTC))

    rig.overrides["start_run"] = refuse

    code = rig.run("collect")

    out, err = capsys.readouterr()
    assert code == 3
    assert err == "Another collection run (id 7) is in progress since 2026-10-30T09:00:00Z.\n"
    assert out == ""
    assert rig.scraper.scrape_calls == []
    assert "fail_run" not in rig.names()


def test_ut073_invalid_configuration_exits_2(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Any, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.chdir(tmp_path)  # no `.env` to read
    monkeypatch.setenv("SCRAPE_TERMS", "")

    code = main(["collect"])

    err = capsys.readouterr().err
    assert code == 2
    assert err.startswith("Invalid configuration: SCRAPE_TERMS:")
    assert "must not be empty" in err


def test_ut073_every_invalid_key_gets_its_own_line(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Any, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("SCRAPE_MAX_PAGES", "0")
    monkeypatch.setenv("SCRAPE_DOWNLOAD_DELAY", "0.5")

    assert main(["collect"]) == 2

    err = capsys.readouterr().err.splitlines()
    assert sorted(line.split(":")[1].strip() for line in err) == [
        "SCRAPE_DOWNLOAD_DELAY",
        "SCRAPE_MAX_PAGES",
    ]


def test_ut073_terms_with_the_same_slug_exit_2_naming_both(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Any, capsys: pytest.CaptureFixture[str]
) -> None:
    """UT-073 (review round 7, issue 002): a slug collision fails at config validation."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("SCRAPE_TERMS", "python,Python")

    code = main(["collect"])

    err = capsys.readouterr().err
    assert code == 2
    assert err.startswith("Invalid configuration: SCRAPE_TERMS:")
    assert "'python', 'Python'" in err


def test_ut074_json_prints_one_document_in_the_run_detail_shape(
    rig: Rig, capsys: pytest.CaptureFixture[str]
) -> None:
    rig.scraper.report = two_outcome_report()

    code = rig.run("collect", "--json")

    out = capsys.readouterr().out
    assert code == 0
    document = json.loads(out)  # exactly one JSON document: anything else would not parse
    run = RunDetailShape.model_validate_json(out)
    # The document is also exactly what the API serves: the real response model accepts it.
    api_run = RunDetailOut.model_validate_json(out)
    assert api_run.model_dump(mode="json") == RunDetailShape.model_validate_json(out).model_dump(
        mode="json"
    )
    assert api_run.totals.model_dump() == {"new": 1, "seen_again": 0, "discarded": 1}
    assert run.status == "success"
    assert run.trigger == "manual"
    assert run.error is None
    assert run.finished_at is not None
    assert [(r.source, r.term, r.status) for r in run.results] == [
        ("vagas", "python", "success"),
        ("infojobs", "python", "success"),
    ]
    # "Desenvolvedor Python Senior" is stored, "Analista de Suporte" is discarded.
    assert run.totals.model_dump() == {"new": 1, "seen_again": 0, "discarded": 1}
    assert document["started_at"] == "2026-10-30T12:00:00Z"
    assert out.count("\n") == 1


def test_ut075_crawl_crash_records_the_crash_message_and_exits_1(
    rig: Rig, capsys: pytest.CaptureFixture[str]
) -> None:
    rig.scraper.error = ScrapeCrashedError("boom")

    code = rig.run("collect")

    assert code == 1
    assert len(rig.fail_run_messages()) == 1
    assert "boom" in rig.fail_run_messages()[0]
    assert capsys.readouterr().err == "Collection run 1 failed: boom\n"
    assert rig.store.runs[1].status is RunStatus.FAILED
    assert rig.store.runs[1].error == "boom"
    assert "complete_run" not in rig.names()


def test_ut075_an_unexpected_crawl_exception_still_fails_the_run(
    rig: Rig, capsys: pytest.CaptureFixture[str]
) -> None:
    rig.scraper.error = RuntimeError("reactor exploded")

    assert rig.run("collect") == 1

    assert rig.store.runs[1].error == "crawl failed: RuntimeError: reactor exploded"
    assert capsys.readouterr().err == (
        "Collection run 1 failed: crawl failed: RuntimeError: reactor exploded\n"
    )


@pytest.mark.parametrize(
    "error",
    [
        ConnectionRefusedError("connection refused"),
        OperationalError("SELECT 1", {}, ConnectionRefusedError("refused")),
        TimeoutError("timed out"),
    ],
)
def test_ut076_unreachable_database_on_start_exits_1(
    rig: Rig, capsys: pytest.CaptureFixture[str], error: Exception
) -> None:
    async def unreachable(real: Override, *_: Any) -> int:
        raise error

    rig.overrides["start_run"] = unreachable

    code = rig.run("collect")

    assert code == 1
    assert capsys.readouterr().err == "Cannot connect to the database at db:5432.\n"
    assert rig.scraper.scrape_calls == []


def test_ut076_a_real_engine_against_a_closed_port_exits_1(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The error classification must hold for what asyncpg and SQLAlchemy really raise."""
    settings = Settings(
        _env_file=None,
        scrape_terms="python",
        database_url="postgresql+asyncpg://u:take_jobs_dev@127.0.0.1:1/none",
    )
    deps = replace(build_cli_deps(settings), scraper=FakeScraper())

    assert main(["collect"], deps=deps) == 1

    assert capsys.readouterr().err == "Cannot connect to the database at 127.0.0.1:1.\n"


def test_ut076_unreachable_database_while_recording_a_failure_exits_1(
    rig: Rig, capsys: pytest.CaptureFixture[str]
) -> None:
    async def unreachable(real: Override, *_: Any) -> CollectionRun:
        raise ConnectionRefusedError("gone")

    rig.scraper.error = ScrapeCrashedError("boom")
    rig.overrides["fail_run"] = unreachable

    assert rig.run("collect") == 1

    assert capsys.readouterr().err == "Cannot connect to the database at db:5432.\n"


def test_ut076_an_unexpected_start_error_is_reported_not_raised(
    rig: Rig, capsys: pytest.CaptureFixture[str]
) -> None:
    async def broken(real: Override, *_: Any) -> int:
        raise ValueError("bad state")

    rig.overrides["start_run"] = broken

    assert rig.run("collect") == 1

    assert capsys.readouterr().err == "Collection run could not be started: ValueError: bad state\n"


def test_ut077_build_cli_deps_takes_the_lists_and_terms_from_settings(rig: Rig) -> None:
    settings = Settings(
        _env_file=None, relevance_include_keywords="golang", scrape_terms="desenvolvedor go"
    )

    deps = build_cli_deps(settings)

    assert deps.relevance.is_relevant("Desenvolvedor Golang") is True
    assert deps.relevance.is_relevant("Desenvolvedor Python") is False
    assert deps.settings.scrape_terms == ["desenvolvedor go"]
    assert deps.sources is SOURCES

    scraper = FakeScraper(report=two_outcome_report("desenvolvedor go"))
    code = main(["collect"], deps=replace(rig.deps(settings), scraper=scraper))

    assert code == 0
    assert scraper.scrape_calls == [["desenvolvedor go"]]


def test_ut077_start_run_receives_sources_times_terms(rig: Rig) -> None:
    settings = Settings(_env_file=None, scrape_terms="python,java,python")  # one duplicate

    main(["collect"], deps=rig.deps(settings))

    assert rig.calls[0] == ("start_run", RunTrigger.MANUAL, 4)  # 2 sources x 2 distinct terms
    assert rig.scraper.scrape_calls == [["python", "java", "python"]]


def test_ut078_trigger_is_recorded_and_a_bogus_one_is_a_usage_error(
    rig: Rig, capsys: pytest.CaptureFixture[str]
) -> None:
    assert rig.run("collect", "--trigger", "startup") == 0
    assert rig.store.runs[1].trigger is RunTrigger.STARTUP

    bogus = Rig()
    assert bogus.run("collect", "--trigger", "bogus") == 2
    assert "invalid choice: 'bogus'" in capsys.readouterr().err
    assert bogus.calls == []


def test_ut078_no_command_and_help(capsys: pytest.CaptureFixture[str]) -> None:
    assert main([]) == 2
    assert "required" in capsys.readouterr().err
    assert main(["--help"]) == 0
    assert "collect" in capsys.readouterr().out


def test_ut079_ingest_failure_is_recorded_through_a_new_service_and_exits_1(
    rig: Rig, capsys: pytest.CaptureFixture[str]
) -> None:
    async def integrity_error(real: Override, *_: Any, **__: Any) -> CollectionRun:
        raise IntegrityError("INSERT INTO jobs", {}, Exception("duplicate key"))

    rig.overrides["complete_run"] = integrity_error

    code = rig.run("collect")

    assert code == 1
    (message,) = rig.fail_run_messages()
    assert message.startswith("ingest failed: IntegrityError: ")
    assert rig.opens == 3  # start_run, complete_run, then a NEW context for fail_run
    err = capsys.readouterr().err
    assert err.startswith("Collection run 1 failed: ingest failed: IntegrityError: ")
    assert rig.store.runs[1].status is RunStatus.FAILED
    assert rig.store.runs[1].error == message


# -- UT-104, UT-105 -----------------------------------------------------------------------


def test_ut104_scrape_interrupted_records_interruption_and_exits_4(
    rig: Rig, capsys: pytest.CaptureFixture[str]
) -> None:
    rig.scraper.error = ScrapeInterruptedError("interrupted by signal")

    code = rig.run("collect")

    assert code == 4
    assert rig.fail_run_messages() == ["interrupted by signal"]
    assert capsys.readouterr().err == "Collection run 1 interrupted by signal.\n"
    assert rig.store.runs[1].status is RunStatus.FAILED
    assert rig.store.runs[1].error == "interrupted by signal"
    assert "complete_run" not in rig.names()


def test_ut104_json_mode_still_prints_the_final_run(
    rig: Rig, capsys: pytest.CaptureFixture[str]
) -> None:
    rig.scraper.error = ScrapeInterruptedError("interrupted by signal")

    assert rig.run("collect", "--json") == 4

    out, err = capsys.readouterr()
    document = RunDetailShape.model_validate_json(out)
    assert (document.status, document.error, document.results) == (
        "failed",
        "interrupted by signal",
        [],
    )
    assert err == "Collection run 1 interrupted by signal.\n"


def test_ut105_taken_over_run_is_reported_and_never_failed_a_second_time(
    rig: Rig, capsys: pytest.CaptureFixture[str]
) -> None:
    async def taken_over(real: Override, *_: Any, **__: Any) -> CollectionRun:
        raise RunTakenOverError(1)

    rig.overrides["complete_run"] = taken_over

    code = rig.run("collect")

    assert code == 1
    assert "fail_run" not in rig.names()
    assert capsys.readouterr().err == (
        "Collection run 1 was taken over by another process; its results were discarded.\n"
    )


# -- UT-117: one handler across phases ----------------------------------------------------


def test_ut117_signal_between_start_and_crawl_skips_ingestion(
    rig: Rig, capsys: pytest.CaptureFixture[str]
) -> None:
    original = signal.getsignal(signal.SIGTERM)
    seen: dict[str, Any] = {}

    async def remember_handlers(real: Override, *args: Any) -> int:
        seen["during_start"] = (signal.getsignal(signal.SIGTERM), signal.getsignal(signal.SIGINT))
        return await real(*args)

    def deliver_sigterm() -> None:
        # start_run's asyncio.run has finished: the same handler must still be installed.
        current = (signal.getsignal(signal.SIGTERM), signal.getsignal(signal.SIGINT))
        seen["still_installed"] = current == seen["during_start"] and current[0] != original
        seen["same_for_both_signals"] = current[0] == current[1]
        current[0](signal.SIGTERM, None)

    rig.overrides["start_run"] = remember_handlers
    rig.scraper.on_scrape = deliver_sigterm  # then scrape() still returns a valid report

    code = rig.run("collect")

    assert seen["still_installed"]
    assert seen["same_for_both_signals"]
    assert code == 4
    assert rig.scraper.interrupt_calls == 1  # the handler interrupted the crawl
    assert "complete_run" not in rig.names()
    assert rig.fail_run_messages() == ["interrupted by signal"]
    assert capsys.readouterr().err == "Collection run 1 interrupted by signal.\n"
    assert signal.getsignal(signal.SIGTERM) == original


def test_ut117_sigint_is_handled_by_the_same_handler(rig: Rig) -> None:
    rig.scraper.on_scrape = lambda: handler_for(signal.SIGINT)(signal.SIGINT, None)

    assert rig.run("collect") == 4

    assert rig.scraper.interrupt_calls == 1
    assert rig.fail_run_messages() == ["interrupted by signal"]


def test_ut117_signal_during_ingestion_before_commit_cancels_and_records_interruption(
    rig: Rig, capsys: pytest.CaptureFixture[str]
) -> None:
    async def signal_then_wait(real: Override, *_: Any, **__: Any) -> CollectionRun:
        handler_for()(signal.SIGTERM, None)  # the phase is cancellable here
        await asyncio.sleep(30)  # cancelled long before this ends
        raise AssertionError("the ingestion was not cancelled")

    rig.overrides["complete_run"] = signal_then_wait

    code = rig.run("collect")

    assert code == 4
    assert rig.names().count("get_run") == 1  # the re-read after the cancellation
    assert rig.fail_run_messages() == ["interrupted by signal"]
    assert rig.store.runs[1].status is RunStatus.FAILED
    assert rig.store.runs[1].error == "interrupted by signal"
    err = capsys.readouterr().err
    assert err == "Collection run 1 interrupted by signal.\n"
    assert "taken over" not in err


def test_ut117_signal_during_start_run_lets_it_finish_then_interrupts(
    rig: Rig, capsys: pytest.CaptureFixture[str]
) -> None:
    returned: list[int] = []

    async def signal_after_creating(real: Override, *args: Any) -> int:
        run_id = await real(*args)
        handler_for()(signal.SIGTERM, None)  # start_run is never cancelled
        returned.append(run_id)
        return run_id

    rig.overrides["start_run"] = signal_after_creating

    code = rig.run("collect")

    assert returned == [1]
    assert code == 4
    assert rig.scraper.scrape_calls == []
    assert rig.fail_run_messages() == ["interrupted by signal"]
    assert not [r for r in rig.store.runs.values() if r.status is RunStatus.RUNNING]
    assert capsys.readouterr().err == "Collection run 1 interrupted by signal.\n"


def test_ut117_signal_after_commit_is_late_and_the_finished_run_stands(
    rig: Rig, capsys: pytest.CaptureFixture[str], caplog: pytest.LogCaptureFixture
) -> None:
    async def commit_then_signal(real: Override, *args: Any, **kwargs: Any) -> CollectionRun:
        run = await real(*args, **kwargs)  # runs finish and calls the CLI's before_commit hook
        handler_for()(signal.SIGTERM, None)  # the phase is no longer cancellable
        return run

    rig.overrides["complete_run"] = commit_then_signal

    with caplog.at_level(logging.WARNING, logger="take_jobs.cli.collect"):
        code = rig.run("collect")

    assert code == 0
    (complete_call,) = [call for call in rig.calls if call[0] == "complete_run"]
    assert complete_call[2] is not None  # the CLI passed before_commit
    assert "fail_run" not in rig.names()
    assert "get_run" not in rig.names()
    out, err = capsys.readouterr()
    assert "finished: success" in out
    assert err == ""  # no "taken over", no interruption message
    assert "event=signal_after_finish run_id=1 exit_code=0" in caplog.text
    assert rig.store.runs[1].status is RunStatus.SUCCESS


def test_ut117_signal_during_a_terminal_fail_run_is_late(
    rig: Rig, capsys: pytest.CaptureFixture[str], caplog: pytest.LogCaptureFixture
) -> None:
    async def record_then_signal(real: Override, *args: Any) -> CollectionRun:
        run = await real(*args)
        handler_for()(signal.SIGTERM, None)  # fail_run is flag-only
        return run

    rig.scraper.error = ScrapeCrashedError("boom")
    rig.overrides["fail_run"] = record_then_signal

    with caplog.at_level(logging.WARNING, logger="take_jobs.cli.collect"):
        code = rig.run("collect")

    assert code == 1
    assert rig.fail_run_messages() == ["boom"]  # exactly once, with the crash message
    assert capsys.readouterr().err == "Collection run 1 failed: boom\n"
    assert "event=signal_after_finish run_id=1 exit_code=1" in caplog.text


def test_ut117_signal_while_recording_an_interruption_is_ignored(rig: Rig) -> None:
    async def signal_inside_fail_run(real: Override, *args: Any) -> CollectionRun:
        run = await real(*args)
        handler_for()(signal.SIGTERM, None)  # a second signal while fail_run records
        return run

    rig.scraper.error = ScrapeInterruptedError("interrupted by signal")
    rig.overrides["fail_run"] = signal_inside_fail_run

    assert rig.run("collect") == 4

    assert rig.fail_run_messages() == ["interrupted by signal"]
    assert rig.scraper.interrupt_calls == 0  # not routed to the (finished) crawl


def test_ut117_cancellation_landing_after_commit_is_a_late_signal(
    rig: Rig, capsys: pytest.CaptureFixture[str], caplog: pytest.LogCaptureFixture
) -> None:
    async def commit_then_cancel(real: Override, *args: Any, **kwargs: Any) -> CollectionRun:
        await real(*args, **kwargs)  # the run is now `success`
        raise asyncio.CancelledError  # the cancel that was queued just before before_commit

    rig.overrides["complete_run"] = commit_then_cancel

    with caplog.at_level(logging.WARNING, logger="take_jobs.cli.collect"):
        code = rig.run("collect")

    assert code == 0
    assert rig.names().count("get_run") == 1
    assert "fail_run" not in rig.names()
    out, err = capsys.readouterr()
    assert "Collection run 1 finished: success in " in out  # printed from the re-read run
    assert err == ""
    assert "event=signal_after_finish run_id=1 exit_code=0" in caplog.text


def test_ut117_a_cancelled_phase_whose_run_failed_elsewhere_exits_with_its_code(
    rig: Rig, capsys: pytest.CaptureFixture[str]
) -> None:
    async def cancelled_after_failure(real: Override, *args: Any, **kwargs: Any) -> CollectionRun:
        run_id = args[0]
        rig.store.runs[run_id] = replace(
            rig.store.runs[run_id],
            status=RunStatus.FAILED,
            finished_at=NOW,
            error="ingest failed: elsewhere",
        )
        raise asyncio.CancelledError

    rig.overrides["complete_run"] = cancelled_after_failure

    assert rig.run("collect") == 1  # the re-read run is finished, `failed`: its code is 1

    assert "fail_run" not in rig.names()
    assert "finished: failed in" in capsys.readouterr().out


def test_ut117_handlers_are_restored_even_when_the_command_fails(rig: Rig) -> None:
    async def explode(real: Override, *_: Any) -> int:
        raise ValueError("bad")

    rig.overrides["start_run"] = explode
    before = signal.getsignal(signal.SIGTERM)

    assert rig.run("collect") == 1

    assert signal.getsignal(signal.SIGTERM) == before


def test_ut117_a_late_second_command_gets_a_fresh_handler_and_fresh_state(rig: Rig) -> None:
    """Two commands in one process (as the integration tests do): the stop flag of the first
    one never leaks into the second."""
    rig.scraper.on_scrape = lambda: handler_for()(signal.SIGTERM, None)
    assert rig.run("collect") == 4

    second = Rig()
    assert second.run("collect") == 0
