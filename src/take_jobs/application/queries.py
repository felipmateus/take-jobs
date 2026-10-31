"""Types the query use cases exchange with their callers (API and CLI)."""

from dataclasses import dataclass, fields
from datetime import date
from typing import Self

from take_jobs.domain.models import Job, Seniority


@dataclass(frozen=True, slots=True)
class JobQuery:
    """Raw search inputs, as the API receives them (dates, not instants)."""

    q: str | None = None
    sources: frozenset[str] = frozenset()
    location: str | None = None
    seniorities: frozenset[Seniority] = frozenset()
    seen_from: date | None = None
    seen_to: date | None = None
    include_inactive: bool = False
    page: int = 1
    size: int = 20


@dataclass(frozen=True, slots=True)
class JobView(Job):
    """A `Job` plus its activity, computed at read time (rule 9)."""

    active: bool

    @classmethod
    def of(cls, job: Job, *, active: bool) -> Self:
        return cls(**{field.name: getattr(job, field.name) for field in fields(Job)}, active=active)
