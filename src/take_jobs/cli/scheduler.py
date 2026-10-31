"""`take-jobs scheduler`: the daily cron, the startup catch-up and signal forwarding (ADR-004).

Start-up order (`_spec.md` > Scheduler start-up, review round 3, issue 003):

1. create the scheduler object (not started) and install the shutdown handler, so a stop during
   any later step (the probe, the startup collection) is forwarded to the running collector;
2. wait for the database;
3. register the cron job and log `scheduler_started`;
4. apply rule 14 (`run_startup`), which blocks while the startup collection runs;
5. start the scheduler loop.

The shutdown handler stops the scheduler loop, sends SIGTERM to the running collector and raises
`SystemExit(0)`. Nothing here blocks in `Popen.wait()`: the runner polls (review round 4,
issue 002).
"""

import asyncio
import logging
import signal
from collections.abc import Callable
from contextlib import AbstractAsyncContextManager
from types import FrameType

from apscheduler.schedulers.base import BaseScheduler
from apscheduler.triggers.cron import CronTrigger

from take_jobs.application.services import CollectionService
from take_jobs.cli.deps import CliDeps
from take_jobs.cli.runner import CollectionRunner
from take_jobs.config import Settings
from take_jobs.domain.models import RunTrigger
from take_jobs.domain.rules import to_standard_crontab

logger = logging.getLogger(__name__)

EXIT_DATABASE_UNAVAILABLE = 1
SHUTDOWN_WAIT_S = 25
PROBE_MAX_WAIT_S = 60
PROBE_DELAYS_S = (1, 2, 4, 8, 10)  # the last delay repeats
JOB_ID = "scheduled_collection"
MISFIRE_GRACE_TIME_S = 3600


class DatabaseUnavailableError(Exception):
    """The start-up probe still failed after `max_wait_s` of backoff."""


def wait_for_database(
    open_service: Callable[[], AbstractAsyncContextManager[CollectionService]],
    *,
    sleep: Callable[[float], None],
    max_wait_s: float = PROBE_MAX_WAIT_S,
) -> None:
    """Ping the database, retrying with backoff 1, 2, 4, 8, 10, 10 ... seconds.

    Every attempt opens its own engine inside its own `asyncio.run`. Raises
    `DatabaseUnavailableError` once the delays slept so far reach `max_wait_s`.
    """

    async def probe() -> None:
        async with open_service() as service:
            await service.ping()

    waited = 0.0
    attempt = 0
    while True:
        attempt += 1
        try:
            asyncio.run(probe())
            return
        except Exception as error:  # any failure to reach the database; SystemExit passes through
            logger.warning(
                "event=startup_probe_failed attempt=%s waited_s=%s error=%s: %s",
                attempt,
                waited,
                type(error).__name__,
                error,
            )
            if waited >= max_wait_s:
                raise DatabaseUnavailableError(
                    f"database unreachable after {waited:g}s ({attempt} attempts)"
                ) from error
        delay = PROBE_DELAYS_S[min(attempt - 1, len(PROBE_DELAYS_S) - 1)]
        sleep(delay)
        waited += delay


def run_startup(deps: CliDeps) -> str | None:
    """Rule 14. Runs a `startup` collection when it applies and returns its reason, else `None`."""
    if not deps.settings.scrape_on_start:
        logger.info("event=startup_collection_skipped reason=disabled")
        return None

    async def reason() -> str | None:
        async with deps.open_collection_service() as service:
            return await service.startup_reason()

    why = asyncio.run(reason())
    if why is None:
        logger.info("event=startup_collection_skipped reason=recent_run_exists")
        return None
    logger.info("event=startup_collection reason=%s", why)
    deps.runner.run(RunTrigger.STARTUP)
    return why


def _build_trigger(settings: Settings) -> CronTrigger:
    return CronTrigger.from_crontab(
        to_standard_crontab(settings.scrape_cron), timezone=settings.scrape_timezone
    )


def configure_scheduler(scheduler: BaseScheduler, deps: CliDeps) -> None:
    """Add the daily collection as the only job. Does not start the scheduler."""
    runner = deps.runner

    def collect_scheduled() -> None:
        logger.info("event=collection_triggered trigger=%s", RunTrigger.SCHEDULED.value)
        runner.run(RunTrigger.SCHEDULED)

    scheduler.add_job(
        collect_scheduled,
        _build_trigger(deps.settings),
        id=JOB_ID,
        max_instances=1,
        coalesce=True,
        misfire_grace_time=MISFIRE_GRACE_TIME_S,
    )


def make_shutdown_handler(
    scheduler: BaseScheduler, runner: CollectionRunner, *, wait_s: float = SHUTDOWN_WAIT_S
) -> Callable[[int, FrameType | None], None]:
    """The SIGTERM/SIGINT handler: stop the loop, forward SIGTERM to the collector, exit `0`.

    It never logs, because a handler can interrupt the main thread inside a logging call.
    """

    def handle(signum: int, frame: FrameType | None) -> None:
        if scheduler.running:
            scheduler.shutdown(wait=False)
        runner.terminate_current(wait_s)
        raise SystemExit(0)

    return handle


def run_scheduler(deps: CliDeps) -> int:
    """Start the scheduler process. Returns `1` when the database never answers; a stop signal
    ends it with `SystemExit(0)`."""
    scheduler = deps.scheduler_factory()
    handler = make_shutdown_handler(scheduler, deps.runner)
    previous = {
        signum: signal.signal(signum, handler) for signum in (signal.SIGTERM, signal.SIGINT)
    }
    try:
        try:
            wait_for_database(deps.open_collection_service, sleep=deps.sleep)
        except DatabaseUnavailableError as error:
            logger.error("event=scheduler_failed reason=database_unavailable error=%s", error)
            return EXIT_DATABASE_UNAVAILABLE
        configure_scheduler(scheduler, deps)
        next_run = _build_trigger(deps.settings).get_next_fire_time(None, deps.clock.now())
        logger.info(
            "event=scheduler_started cron=%r timezone=%s next_run=%s",
            deps.settings.scrape_cron,
            deps.settings.scrape_timezone,
            None if next_run is None else next_run.isoformat(),
        )
        run_startup(deps)
        scheduler.start()
        return 0
    except SystemExit:
        logger.info("event=scheduler_stopped")
        raise
    finally:
        for signum, old in previous.items():
            signal.signal(signum, signal.SIG_DFL if old is None else old)
