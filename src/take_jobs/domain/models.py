"""Domain entities, value objects and enums (stdlib only; ADR-001)."""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum
from typing import Self


class Seniority(StrEnum):
    INTERN = "intern"
    JUNIOR = "junior"
    MID = "mid"
    SENIOR = "senior"


class RunTrigger(StrEnum):
    SCHEDULED = "scheduled"
    STARTUP = "startup"
    MANUAL = "manual"


class RunStatus(StrEnum):
    RUNNING = "running"
    SUCCESS = "success"
    PARTIAL = "partial"
    FAILED = "failed"


class ResultStatus(StrEnum):
    SUCCESS = "success"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class ScrapedJob:
    source: str  # registered source id, e.g. "vagas"
    external_id: str  # the site's own job id
    title: str
    url: str
    company: str | None
    location: str | None
    description: str | None
    published_label: str | None  # publication date as displayed by the site


@dataclass(frozen=True, slots=True)
class CombinationOutcome:
    source: str
    term: str
    jobs: tuple[ScrapedJob, ...]  # in collection order, may contain repeats
    pages: int
    error: str | None  # None = success


@dataclass(frozen=True, slots=True)
class ScrapeReport:
    outcomes: tuple[CombinationOutcome, ...]  # one per source x term


@dataclass(frozen=True, slots=True)
class Job:
    id: int
    source: str
    external_id: str
    title: str
    url: str
    company: str | None
    location: str | None
    description: str | None
    published_label: str | None
    seniority: Seniority | None
    first_seen_at: datetime
    last_seen_at: datetime

    def is_active(self, now: datetime, inactive_after: timedelta) -> bool:
        """Rule 9: active while `now - last_seen_at <= inactive_after` (never stored)."""
        return now - self.last_seen_at <= inactive_after


@dataclass(frozen=True, slots=True)
class JobSearchCriteria:
    text: str | None = None
    sources: frozenset[str] = frozenset()
    location: str | None = None
    seniorities: frozenset[Seniority] = frozenset()
    seen_from: datetime | None = None  # start of day in SCRAPE_TIMEZONE, as UTC
    seen_to: datetime | None = None  # end of day in SCRAPE_TIMEZONE, as UTC
    active_since: datetime | None = None  # None = include inactive
    page: int = 1
    size: int = 20


@dataclass(frozen=True, slots=True)
class Page[T]:
    items: tuple[T, ...]
    total: int
    page: int
    size: int

    @property
    def pages(self) -> int:
        return -(-self.total // self.size)


@dataclass(frozen=True, slots=True)
class CombinationResult:
    source: str
    term: str
    status: ResultStatus
    pages: int
    new: int
    seen_again: int
    discarded: int
    error: str | None


@dataclass(frozen=True, slots=True)
class RunTotals:
    new: int
    seen_again: int
    discarded: int

    @classmethod
    def from_results(cls, results: Sequence[CombinationResult]) -> Self:
        """Sum the per-combination counters; zeros when there are no results."""
        return cls(
            new=sum(result.new for result in results),
            seen_again=sum(result.seen_again for result in results),
            discarded=sum(result.discarded for result in results),
        )


@dataclass(frozen=True, slots=True)
class CollectionRun:
    id: int
    trigger: RunTrigger
    status: RunStatus
    started_at: datetime
    finished_at: datetime | None
    error: str | None
    expected_combinations: int  # sources x terms at start; denominator for O5
    totals: RunTotals  # filled by the repository from an aggregate over results,
    # so list views carry real totals while `results` is empty
    results: tuple[CombinationResult, ...]  # empty while running and in list views
