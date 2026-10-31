"""`take-jobs collect`: one run = start (async DB) -> crawl (spawned child) -> ingest (async DB).

This module owns the signal-safe run lifecycle (`_spec.md` data flow step 1, rule 24, ADR-002):

- **One handler.** A single process-wide `signal.signal` handler for SIGTERM and SIGINT stays
  installed for the whole command and the original handlers come back on return.
  `loop.add_signal_handler` is never used: when its loop closes it resets the signal to the
  default action instead of restoring the previous handler.
- **What a signal does** depends on the current phase, kept in a phase-scoped reference:
  the crawl is interrupted through `scraper.interrupt()`; ingestion is cancelled
  (`loop.call_soon_threadsafe(task.cancel)`) only while the phase is `cancellable`, which
  `CollectionService.complete_run` clears through `before_commit` right before the commit;
  `start_run`, every `fail_run`, the status re-read and the gaps between phases only set the flag.
- **After each non-terminal phase** (`start_run`, the crawl) the stop flag is checked. After a
  terminal phase (`complete_run` committed, or a crash or ingest-failure `fail_run`) a set flag is
  a late signal: it is logged and the phase's own exit code stands.
- **After a `CancelledError`** the run is re-read with `get_run`: a finished run means the commit
  landed (late signal); a `running` run is recorded as interrupted. "Taken over by another
  process" is printed only when `complete_run` itself raises `RunTakenOverError`.

Handlers run in the main thread between bytecodes, so the handler does nothing that could block on
a lock held by the interrupted code: it never logs.
"""

import asyncio
import logging
import signal
import sys
from contextlib import suppress
from enum import Enum, auto
from types import FrameType

from sqlalchemy.engine import make_url
from sqlalchemy.exc import InterfaceError, OperationalError
from sqlalchemy.exc import TimeoutError as SqlAlchemyTimeoutError

from take_jobs.cli import output
from take_jobs.cli.deps import CliDeps
from take_jobs.domain.errors import (
    RunAlreadyActiveError,
    RunTakenOverError,
    ScrapeCrashedError,
    ScrapeInterruptedError,
)
from take_jobs.domain.models import CollectionRun, RunStatus, RunTrigger, ScrapeReport

logger = logging.getLogger(__name__)

EXIT_INTERRUPTED = 4
INTERRUPTED_ERROR = "interrupted by signal"
_SIGNALS = (signal.SIGTERM, signal.SIGINT)
_CONNECTION_ERRORS = (OSError, OperationalError, InterfaceError, SqlAlchemyTimeoutError)


class _Kind(Enum):
    IDLE = auto()  # between phases: only the flag is set
    START = auto()  # start_run: never cancelled
    CRAWL = auto()  # the signal interrupts the scraper
    INGEST = auto()  # complete_run: cancellable until `before_commit`
    TERMINAL = auto()  # fail_run and the status re-read: never cancelled


class _Phase:
    """The phase-scoped reference the signal handler reads. A new one per phase, so a loop or
    task of an earlier phase can never be reached."""

    def __init__(self, kind: _Kind) -> None:
        self.kind = kind
        self.cancellable = False
        self._loop: asyncio.AbstractEventLoop | None = None
        self._task: asyncio.Task[object] | None = None
        self._cancel_sent = False

    def attach(self, loop: asyncio.AbstractEventLoop, task: asyncio.Task[object]) -> None:
        self._loop, self._task, self.cancellable = loop, task, True

    def clear_cancellable(self) -> None:
        """Passed to `complete_run` as `before_commit`: after this, a signal cannot cancel."""
        self.cancellable = False

    def cancel(self) -> None:
        if not self.cancellable or self._cancel_sent or self._loop is None or self._task is None:
            return
        self._cancel_sent = True  # one cancellation only, so cleanup is not cancelled again
        with suppress(RuntimeError):  # the loop closed in the meantime: nothing left to cancel
            self._loop.call_soon_threadsafe(self._task.cancel)


class _Done(Exception):
    """Internal: the command is over with this exit code."""

    def __init__(self, code: int) -> None:
        super().__init__(code)
        self.code = code


class _Crawl:
    def __init__(
        self,
        report: ScrapeReport | None = None,
        error: str | None = None,
        interrupted: bool = False,
    ) -> None:
        self.report = report
        self.error = error
        self.interrupted = interrupted


def run_collect(deps: CliDeps, trigger: RunTrigger, *, json_output: bool) -> int:
    """Run one collection and return the exit code (0, 1, 3 or 4; 2 is the caller's)."""
    return _Collector(deps, trigger, json_output).run()


class _Collector:
    def __init__(self, deps: CliDeps, trigger: RunTrigger, json_output: bool) -> None:
        self._deps = deps
        self._trigger = trigger
        self._json = json_output
        self._stop_requested = False
        self._phase = _Phase(_Kind.IDLE)

    # -- signals ----------------------------------------------------------------------------

    def _on_signal(self, signum: int, frame: FrameType | None) -> None:
        self._stop_requested = True
        phase = self._phase
        if phase.kind is _Kind.CRAWL:
            self._deps.scraper.interrupt()
        elif phase.kind is _Kind.INGEST:
            phase.cancel()
        # START, TERMINAL and IDLE: flag only.

    def _enter(self, kind: _Kind) -> _Phase:
        self._phase = _Phase(kind)
        return self._phase

    def run(self) -> int:
        previous = {}
        try:
            for signum in _SIGNALS:
                previous[signum] = signal.signal(signum, self._on_signal)
            return self._collect()
        except _Done as done:
            return done.code
        finally:
            for signum, handler in previous.items():
                signal.signal(signum, signal.SIG_DFL if handler is None else handler)

    # -- the run ----------------------------------------------------------------------------

    def _collect(self) -> int:
        deps = self._deps
        terms = list(deps.settings.scrape_terms)
        expected = len(deps.sources) * len(set(terms))

        run_id = self._start(expected)
        if not self._json:
            self._say(output.started_line(run_id, self._trigger))
        if self._stop_requested:
            return self._interrupted(run_id)

        crawl = self._crawl(terms)
        if crawl.interrupted or self._stop_requested:
            return self._interrupted(run_id)
        if crawl.error is not None or crawl.report is None:
            return self._fail(run_id, crawl.error or "crawl produced no report")
        return self._ingest(run_id, crawl.report)

    def _start(self, expected_combinations: int) -> int:
        self._enter(_Kind.START)
        failure: Exception | None = None
        run_id = 0
        try:
            run_id = asyncio.run(self._start_run(expected_combinations))
        except Exception as exc:
            failure = exc
        self._enter(_Kind.IDLE)
        if isinstance(failure, RunAlreadyActiveError):
            self._complain(output.already_active_message(failure.run_id, failure.started_at))
            raise _Done(3)
        if failure is not None:
            raise _Done(self._unexpected(failure, "Collection run could not be started"))
        return run_id

    def _crawl(self, terms: list[str]) -> _Crawl:
        self._enter(_Kind.CRAWL)
        # A signal that landed after the check in `_collect` but before this phase only set the
        # flag; skip the crawl rather than run it to the end.
        if self._stop_requested:
            self._enter(_Kind.IDLE)
            return _Crawl(interrupted=True)
        result = _Crawl()
        try:
            result.report = self._deps.scraper.scrape(terms)
        except ScrapeInterruptedError:
            result.interrupted = True
        except ScrapeCrashedError as exc:
            result.error = str(exc)
        except Exception as exc:  # whatever else the crawl raised, the run must not stay running
            result.error = f"crawl failed: {type(exc).__name__}: {exc}"
        self._enter(_Kind.IDLE)
        return result

    def _ingest(self, run_id: int, report: ScrapeReport) -> int:
        phase = self._enter(_Kind.INGEST)
        failure: BaseException | None = None
        run: CollectionRun | None = None
        try:
            run = asyncio.run(self._complete_run(phase, run_id, report))
        except (asyncio.CancelledError, Exception) as exc:
            failure = exc
        self._enter(_Kind.IDLE)

        if isinstance(failure, asyncio.CancelledError):
            return self._after_cancellation(run_id)
        if isinstance(failure, RunTakenOverError):
            return self._taken_over(run_id)
        if failure is not None:
            message = f"ingest failed: {type(failure).__name__}: {failure}"
            return self._fail(run_id, message)
        assert run is not None
        if self._stop_requested:
            self._log_late_signal(run_id, output.exit_code_for(run.status))
        return self._report(run)

    def _after_cancellation(self, run_id: int) -> int:
        """The ingestion task was cancelled: the run's own status decides (data flow step 1)."""
        self._enter(_Kind.TERMINAL)
        failure: Exception | None = None
        run: CollectionRun | None = None
        try:
            run = asyncio.run(self._get_run(run_id))
        except Exception as exc:
            failure = exc
        self._enter(_Kind.IDLE)
        if failure is not None:
            return self._unexpected(failure, f"Collection run {run_id} could not be re-read")
        if run is not None and run.status is not RunStatus.RUNNING:
            # The commit landed before the cancellation took effect: a late signal.
            self._log_late_signal(run_id, output.exit_code_for(run.status))
            return self._report(run)
        return self._interrupted(run_id)

    # -- terminal outcomes ------------------------------------------------------------------

    def _fail(self, run_id: int, message: str) -> int:
        """Crash or ingest failure: record `failed`, exit 1. A signal now is a late signal."""
        run = self._record_failure(run_id, message)
        self._complain(f"Collection run {run_id} failed: {message}")
        if self._json:
            self._say(output.run_as_json(run))
        if self._stop_requested:
            self._log_late_signal(run_id, 1)
        return 1

    def _interrupted(self, run_id: int) -> int:
        run = self._record_failure(run_id, INTERRUPTED_ERROR)
        self._complain(f"Collection run {run_id} {INTERRUPTED_ERROR}.")
        if self._json:
            self._say(output.run_as_json(run))
        return EXIT_INTERRUPTED

    def _record_failure(self, run_id: int, message: str) -> CollectionRun:
        """`fail_run` in a fresh transaction. Never cancelled: further signals only set the flag."""
        self._enter(_Kind.TERMINAL)
        failure: Exception | None = None
        run: CollectionRun | None = None
        try:
            run = asyncio.run(self._fail_run(run_id, message))
        except Exception as exc:
            failure = exc
        self._enter(_Kind.IDLE)
        if isinstance(failure, RunTakenOverError):
            raise _Done(self._taken_over(run_id))
        if failure is not None:
            raise _Done(self._unexpected(failure, f"Collection run {run_id} could not be recorded"))
        assert run is not None
        return run

    def _report(self, run: CollectionRun) -> int:
        if self._json:
            self._say(output.run_as_json(run))
        else:
            for line in output.summary_lines(run):
                self._say(line)
        return output.exit_code_for(run.status)

    def _taken_over(self, run_id: int) -> int:
        self._complain(
            f"Collection run {run_id} was taken over by another process; "
            "its results were discarded."
        )
        return 1

    def _unexpected(self, exc: Exception, context: str) -> int:
        if _is_connection_error(exc):
            self._complain(self._cannot_connect_message())
        else:
            self._complain(f"{context}: {type(exc).__name__}: {exc}")
        return 1

    def _cannot_connect_message(self) -> str:
        url = make_url(self._deps.settings.database_url)
        return f"Cannot connect to the database at {url.host or 'localhost'}:{url.port or 5432}."

    def _log_late_signal(self, run_id: int, exit_code: int) -> None:
        logger.warning("event=signal_after_finish run_id=%s exit_code=%s", run_id, exit_code)

    # -- phases that touch the database: each opens its own service (and engine) ------------

    async def _start_run(self, expected_combinations: int) -> int:
        async with self._deps.open_collection_service() as service:
            return await service.start_run(self._trigger, expected_combinations)

    async def _complete_run(
        self, phase: _Phase, run_id: int, report: ScrapeReport
    ) -> CollectionRun:
        task = asyncio.current_task()
        assert task is not None
        phase.attach(asyncio.get_running_loop(), task)
        if self._stop_requested:  # a signal that landed while the loop was starting
            raise asyncio.CancelledError
        async with self._deps.open_collection_service() as service:
            return await service.complete_run(run_id, report, before_commit=phase.clear_cancellable)

    async def _get_run(self, run_id: int) -> CollectionRun | None:
        async with self._deps.open_collection_service() as service:
            return await service.get_run(run_id)

    async def _fail_run(self, run_id: int, message: str) -> CollectionRun:
        async with self._deps.open_collection_service() as service:
            return await service.fail_run(run_id, message)

    # -- terminal I/O -----------------------------------------------------------------------

    @staticmethod
    def _say(line: str) -> None:
        print(line, file=sys.stdout, flush=True)

    @staticmethod
    def _complain(line: str) -> None:
        print(line, file=sys.stderr, flush=True)


def _is_connection_error(exc: BaseException) -> bool:
    return isinstance(exc, _CONNECTION_ERRORS)
