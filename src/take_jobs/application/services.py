"""Use cases called by the CLI and the API. They depend on domain ports only (ADR-001)."""

from collections.abc import Callable
from contextlib import suppress
from dataclasses import replace
from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from take_jobs.application.errors import (
    CollectionRunNotFoundError,
    InvalidPeriodError,
    JobNotFoundError,
)
from take_jobs.application.queries import JobQuery, JobView
from take_jobs.domain.errors import RunAlreadyActiveError, RunTakenOverError
from take_jobs.domain.models import (
    CollectionRun,
    CombinationOutcome,
    CombinationResult,
    JobSearchCriteria,
    Page,
    ResultStatus,
    RunStatus,
    RunTotals,
    RunTrigger,
    ScrapeReport,
)
from take_jobs.domain.ports import (
    Clock,
    CollectionRunRepository,
    JobRepository,
    UnitOfWork,
)
from take_jobs.domain.rules import (
    RelevancePolicy,
    classify_seniority,
    final_run_status,
    startup_collection_reason,
)

__all__ = [
    "CollectionRunQueryService",
    "CollectionService",
    "JobQuery",
    "JobQueryService",
    "JobView",
]

_UTC_TICK = timedelta(microseconds=1)


def _blank_to_none(value: str | None) -> str | None:
    if value is None:
        return None
    stripped = value.strip()
    return stripped or None


class JobQueryService:
    def __init__(
        self, jobs: JobRepository, clock: Clock, inactive_after: timedelta, tz: ZoneInfo
    ) -> None:
        self._jobs = jobs
        self._clock = clock
        self._inactive_after = inactive_after
        self._tz = tz

    async def search(self, query: JobQuery) -> Page[JobView]:
        if (
            query.seen_from is not None
            and query.seen_to is not None
            and query.seen_from > query.seen_to
        ):
            raise InvalidPeriodError(query.seen_from, query.seen_to)
        now = self._clock.now()
        criteria = JobSearchCriteria(
            text=_blank_to_none(query.q),
            sources=query.sources,
            location=_blank_to_none(query.location),
            seniorities=query.seniorities,
            seen_from=None if query.seen_from is None else self._start_of_day(query.seen_from),
            seen_to=None if query.seen_to is None else self._end_of_day(query.seen_to),
            active_since=None if query.include_inactive else now - self._inactive_after,
            page=query.page,
            size=query.size,
        )
        found = await self._jobs.search(criteria)
        return Page(
            items=tuple(
                JobView.of(job, active=job.is_active(now, self._inactive_after))
                for job in found.items
            ),
            total=found.total,
            page=found.page,
            size=found.size,
        )

    async def get(self, job_id: int) -> JobView:
        job = await self._jobs.get(job_id)
        if job is None:
            raise JobNotFoundError(job_id)
        return JobView.of(job, active=job.is_active(self._clock.now(), self._inactive_after))

    def _start_of_day(self, day: date) -> datetime:
        return datetime.combine(day, time.min, tzinfo=self._tz).astimezone(UTC)

    def _end_of_day(self, day: date) -> datetime:
        # Start of the next local day minus one tick, so a DST change never shifts the bound.
        next_start = datetime.combine(day + timedelta(days=1), time.min, tzinfo=self._tz)
        return next_start.astimezone(UTC) - _UTC_TICK


class CollectionRunQueryService:
    def __init__(self, runs: CollectionRunRepository) -> None:
        self._runs = runs

    async def list(self, page: int, size: int) -> Page[CollectionRun]:
        return await self._runs.list(page, size)

    async def get(self, run_id: int) -> CollectionRun:
        run = await self._runs.get(run_id)
        if run is None:
            raise CollectionRunNotFoundError(run_id)
        return run


class CollectionService:
    def __init__(
        self,
        uow_factory: Callable[[], UnitOfWork],
        relevance: RelevancePolicy,
        clock: Clock,
        run_timeout: timedelta,
    ) -> None:
        self._uow_factory = uow_factory
        self._relevance = relevance
        self._clock = clock
        self._run_timeout = run_timeout

    async def start_run(self, trigger: RunTrigger, expected_combinations: int) -> int:
        """Rule 13: refuse while a live run exists; a run older than the timeout is first
        marked interrupted (it can only belong to a dead process)."""
        async with self._uow_factory() as uow:
            now = self._clock.now()
            active = await uow.runs.get_active()
            if active is not None:
                if now - active.started_at <= self._run_timeout:
                    raise RunAlreadyActiveError(active.id, active.started_at)
                # If another process already ended it, `start` decides what is left.
                with suppress(RunTakenOverError):
                    await uow.runs.mark_interrupted(active.id, now)
            return await uow.runs.start(trigger, now, expected_combinations)

    async def complete_run(
        self,
        run_id: int,
        report: ScrapeReport,
        *,
        before_commit: Callable[[], None] | None = None,
    ) -> CollectionRun:
        """Ingest the report and finish the run in one transaction (ADR-002).

        `before_commit` runs synchronously as the last statement inside the unit of work, so
        `UnitOfWork.__aexit__` commits right after it. It is not called when anything before it
        raises."""
        async with self._uow_factory() as uow:
            run = await uow.runs.get(run_id)
            if run is None or run.status is not RunStatus.RUNNING:
                raise RunTakenOverError(run_id)
            seen_at = self._clock.now()
            results = [await self._ingest(uow, outcome, seen_at) for outcome in report.outcomes]
            status = final_run_status(results)
            await uow.runs.finish(run_id, status, results, seen_at, None)
            if before_commit is not None:
                before_commit()
        return replace(
            run,
            status=status,
            finished_at=seen_at,
            totals=RunTotals.from_results(results),
            results=tuple(results),
        )

    async def get_run(self, run_id: int) -> CollectionRun | None:
        async with self._uow_factory() as uow:
            return await uow.runs.get(run_id)

    async def fail_run(self, run_id: int, error: str) -> CollectionRun:
        """Record the whole run as failed, in a fresh transaction. Results stay empty."""
        async with self._uow_factory() as uow:
            await uow.runs.finish(run_id, RunStatus.FAILED, (), self._clock.now(), error)
            run = await uow.runs.get(run_id)
        if run is None:  # finish succeeded a moment ago, so the row cannot have vanished
            raise RunTakenOverError(run_id)
        return run

    async def startup_reason(self) -> str | None:
        """Rule 14."""
        async with self._uow_factory() as uow:
            store_empty = await uow.probe.is_empty()
            latest = await uow.runs.latest_finished()
            return startup_collection_reason(
                store_empty, None if latest is None else latest.started_at, self._clock.now()
            )

    async def ping(self) -> None:
        async with self._uow_factory() as uow:
            await uow.probe.ping()

    async def _ingest(
        self, uow: UnitOfWork, outcome: CombinationOutcome, seen_at: datetime
    ) -> CombinationResult:
        new = seen_again = discarded = 0
        for job in outcome.jobs:
            if not self._relevance.is_relevant(job.title):
                discarded += 1
            elif await uow.jobs.upsert(job, classify_seniority(job.title), seen_at):
                new += 1
            else:
                seen_again += 1  # stored before: in an earlier run or earlier in this one (rule 3)
        return CombinationResult(
            source=outcome.source,
            term=outcome.term,
            status=ResultStatus.FAILED if outcome.error is not None else ResultStatus.SUCCESS,
            pages=outcome.pages,
            new=new,
            seen_again=seen_again,
            discarded=discarded,
            error=outcome.error,
        )
