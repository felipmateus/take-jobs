"""In-memory fakes of the domain ports, shared by unit tests (application, CLI, scheduler).

`InMemoryStore` holds the data and an event log. `InMemoryUnitOfWork(store)` snapshots the data on
enter and restores it on an exception, so rollback is observable. Events: `start`,
`mark_interrupted`, `upsert:<source>/<external_id>`, `finish`, `commit`, `rollback`. Tests add their
own markers with `store.events.append(...)`.
"""

from collections.abc import Sequence
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime, timedelta
from typing import Self

from take_jobs.domain.errors import RunAlreadyActiveError, RunTakenOverError
from take_jobs.domain.models import (
    CollectionRun,
    CombinationResult,
    Job,
    JobSearchCriteria,
    Page,
    RunStatus,
    RunTotals,
    RunTrigger,
    ScrapedJob,
    Seniority,
)

NOW = datetime(2026, 10, 30, 12, 0, tzinfo=UTC)


class FixedClock:
    def __init__(self, now: datetime = NOW) -> None:
        self._now = now

    def now(self) -> datetime:
        return self._now

    def advance(self, delta: timedelta) -> None:
        self._now += delta


@dataclass
class InMemoryStore:
    jobs: dict[tuple[str, str], Job] = field(default_factory=dict)
    runs: dict[int, CollectionRun] = field(default_factory=dict)
    events: list[str] = field(default_factory=list)
    # Failure injection, raised by the matching operation.
    finish_error: Exception | None = None
    upsert_error: Exception | None = None
    ping_error: Exception | None = None
    # Overrides `is_empty()`; None derives it from `jobs`.
    empty: bool | None = None
    ping_calls: int = 0
    _next_job_id: int = 1
    _next_run_id: int = 1

    def add_job(
        self, job: ScrapedJob, *, seen_at: datetime, seniority: Seniority | None = None
    ) -> Job:
        stored = Job(
            id=self._next_job_id,
            source=job.source,
            external_id=job.external_id,
            title=job.title,
            url=job.url,
            company=job.company,
            location=job.location,
            description=job.description,
            published_label=job.published_label,
            seniority=seniority,
            first_seen_at=seen_at,
            last_seen_at=seen_at,
        )
        self._next_job_id += 1
        self.jobs[(job.source, job.external_id)] = stored
        return stored

    def add_run(
        self,
        *,
        started_at: datetime,
        status: RunStatus = RunStatus.RUNNING,
        trigger: RunTrigger = RunTrigger.MANUAL,
        expected_combinations: int = 24,
        error: str | None = None,
    ) -> CollectionRun:
        run = CollectionRun(
            id=self._next_run_id,
            trigger=trigger,
            status=status,
            started_at=started_at,
            finished_at=None if status is RunStatus.RUNNING else started_at,
            error=error,
            expected_combinations=expected_combinations,
            totals=RunTotals(0, 0, 0),
            results=(),
        )
        self._next_run_id += 1
        self.runs[run.id] = run
        return run

    def snapshot(self) -> tuple[dict[tuple[str, str], Job], dict[int, CollectionRun], int, int]:
        return dict(self.jobs), dict(self.runs), self._next_job_id, self._next_run_id

    def restore(
        self, snapshot: tuple[dict[tuple[str, str], Job], dict[int, CollectionRun], int, int]
    ) -> None:
        self.jobs, self.runs, self._next_job_id, self._next_run_id = (
            dict(snapshot[0]),
            dict(snapshot[1]),
            snapshot[2],
            snapshot[3],
        )


class InMemoryJobRepository:
    def __init__(self, store: InMemoryStore) -> None:
        self._store = store
        self.searches: list[JobSearchCriteria] = []

    async def upsert(self, job: ScrapedJob, seniority: Seniority | None, seen_at: datetime) -> bool:
        store = self._store
        store.events.append(f"upsert:{job.source}/{job.external_id}")
        if store.upsert_error is not None:
            raise store.upsert_error
        key = (job.source, job.external_id)
        existing = store.jobs.get(key)
        if existing is None:
            store.add_job(job, seen_at=seen_at, seniority=seniority)
            return True
        store.jobs[key] = replace(
            existing,
            title=job.title,
            url=job.url,
            company=job.company,
            location=job.location,
            description=job.description,
            published_label=job.published_label,
            seniority=seniority,
            last_seen_at=seen_at,
        )
        return False

    async def get(self, job_id: int) -> Job | None:
        return next((job for job in self._store.jobs.values() if job.id == job_id), None)

    async def search(self, criteria: JobSearchCriteria) -> Page[Job]:
        """Records the criteria and returns every stored job (newest first), without filtering."""
        self.searches.append(criteria)
        ordered = sorted(
            self._store.jobs.values(),
            key=lambda job: (job.last_seen_at, job.first_seen_at, job.id),
            reverse=True,
        )
        start = (criteria.page - 1) * criteria.size
        return Page(
            items=tuple(ordered[start : start + criteria.size]),
            total=len(ordered),
            page=criteria.page,
            size=criteria.size,
        )


class InMemoryJobStoreProbe:
    def __init__(self, store: InMemoryStore) -> None:
        self._store = store

    async def is_empty(self) -> bool:
        if self._store.empty is not None:
            return self._store.empty
        return not self._store.jobs

    async def ping(self) -> None:
        self._store.ping_calls += 1
        if self._store.ping_error is not None:
            raise self._store.ping_error


class InMemoryCollectionRunRepository:
    def __init__(self, store: InMemoryStore) -> None:
        self._store = store

    def _running(self) -> CollectionRun | None:
        return next(
            (run for run in self._store.runs.values() if run.status is RunStatus.RUNNING), None
        )

    async def start(
        self, trigger: RunTrigger, started_at: datetime, expected_combinations: int
    ) -> int:
        active = self._running()
        if active is not None:
            raise RunAlreadyActiveError(active.id, active.started_at)
        self._store.events.append("start")
        return self._store.add_run(
            started_at=started_at, trigger=trigger, expected_combinations=expected_combinations
        ).id

    async def get_active(self) -> CollectionRun | None:
        return self._running()

    async def latest_finished(self) -> CollectionRun | None:
        finished = [r for r in self._store.runs.values() if r.status is not RunStatus.RUNNING]
        return max(finished, key=lambda run: (run.started_at, run.id), default=None)

    def _leave_running(
        self,
        run_id: int,
        status: RunStatus,
        finished_at: datetime,
        error: str | None,
        results: Sequence[CombinationResult],
    ) -> None:
        run = self._store.runs.get(run_id)
        if run is None or run.status is not RunStatus.RUNNING:
            raise RunTakenOverError(run_id)
        self._store.runs[run_id] = replace(
            run,
            status=status,
            finished_at=finished_at,
            error=error,
            totals=RunTotals.from_results(results),
            results=tuple(results),
        )

    async def mark_interrupted(self, run_id: int, finished_at: datetime) -> None:
        self._leave_running(run_id, RunStatus.FAILED, finished_at, "interrupted", ())
        self._store.events.append("mark_interrupted")

    async def finish(
        self,
        run_id: int,
        status: RunStatus,
        results: Sequence[CombinationResult],
        finished_at: datetime,
        error: str | None,
    ) -> None:
        self._store.events.append("finish")
        if self._store.finish_error is not None:
            raise self._store.finish_error
        self._leave_running(run_id, status, finished_at, error, results)

    async def get(self, run_id: int) -> CollectionRun | None:
        return self._store.runs.get(run_id)

    async def list(self, page: int, size: int) -> Page[CollectionRun]:
        ordered = sorted(
            self._store.runs.values(), key=lambda run: (run.started_at, run.id), reverse=True
        )
        start = (page - 1) * size
        items = tuple(replace(run, results=()) for run in ordered[start : start + size])
        return Page(items=items, total=len(ordered), page=page, size=size)


class InMemoryUnitOfWork:
    jobs: InMemoryJobRepository
    runs: InMemoryCollectionRunRepository
    probe: InMemoryJobStoreProbe

    def __init__(self, store: InMemoryStore) -> None:
        self.store = store
        self.jobs = InMemoryJobRepository(store)
        self.runs = InMemoryCollectionRunRepository(store)
        self.probe = InMemoryJobStoreProbe(store)
        self._snapshot: tuple | None = None

    async def __aenter__(self) -> Self:
        self._snapshot = self.store.snapshot()
        return self

    async def __aexit__(self, *exc: object) -> None:
        snapshot, self._snapshot = self._snapshot, None
        if all(item is None for item in exc):
            self.store.events.append("commit")
        else:
            if snapshot is not None:
                self.store.restore(snapshot)
            self.store.events.append("rollback")
