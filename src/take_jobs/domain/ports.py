"""Ports: the `Protocol`s the application layer depends on (stdlib only)."""

from collections.abc import Sequence
from datetime import datetime
from typing import Protocol, Self

from take_jobs.domain.models import (
    CollectionRun,
    CombinationResult,
    Job,
    JobSearchCriteria,
    Page,
    RunStatus,
    RunTrigger,
    ScrapedJob,
    ScrapeReport,
    Seniority,
)


class Clock(Protocol):
    def now(self) -> datetime: ...  # timezone-aware UTC


class JobRepository(Protocol):
    async def upsert(self, job: ScrapedJob, seniority: Seniority | None, seen_at: datetime) -> bool:
        """Insert or refresh by (source, external_id). Returns True when inserted (new)."""

    async def get(self, job_id: int) -> Job | None: ...
    async def search(self, criteria: JobSearchCriteria) -> Page[Job]: ...


class JobStoreProbe(Protocol):
    async def is_empty(self) -> bool: ...
    async def ping(self) -> None: ...  # raises on an unreachable database


class CollectionRunRepository(Protocol):
    async def start(
        self, trigger: RunTrigger, started_at: datetime, expected_combinations: int
    ) -> int:
        """Create a running run. Raises RunAlreadyActiveError(run_id, started_at)."""

    async def get_active(self) -> CollectionRun | None: ...
    async def latest_finished(self) -> CollectionRun | None:
        """Most recently started run whose status is not running (rule 14)."""

    async def mark_interrupted(self, run_id: int, finished_at: datetime) -> None: ...
    async def finish(
        self,
        run_id: int,
        status: RunStatus,
        results: Sequence[CombinationResult],
        finished_at: datetime,
        error: str | None,
    ) -> None:
        """Conditional on status = 'running'. Raises RunTakenOverError when 0 rows are affected."""

    async def get(self, run_id: int) -> CollectionRun | None: ...
    async def list(self, page: int, size: int) -> Page[CollectionRun]: ...


class UnitOfWork(Protocol):
    jobs: JobRepository
    runs: CollectionRunRepository
    probe: JobStoreProbe  # same session; used by CollectionService.ping/startup_reason

    async def __aenter__(self) -> Self: ...
    async def __aexit__(self, *exc: object) -> None: ...  # commit on success, rollback on error


class JobScraper(Protocol):
    def scrape(self, terms: Sequence[str]) -> ScrapeReport:
        """Blocking. One outcome per registered source x term. Never touches the database.
        Raises ScrapeInterruptedError (a signal stopped it) or ScrapeCrashedError (no report)."""

    def interrupt(self) -> None:
        """Called from the collector's signal handler; stops a running crawl within 5 s (rule 24).
        Called before the child exists, it records the request: scrape() then raises
        ScrapeInterruptedError without crawling (checked before and right after process.start())."""
