"""Application errors, plus the domain errors that ports raise (re-exported for callers)."""

from datetime import date

from take_jobs.domain.errors import (
    RunAlreadyActiveError,
    RunTakenOverError,
    ScrapeCrashedError,
    ScrapeInterruptedError,
)

__all__ = [
    "CollectionRunNotFoundError",
    "InvalidPeriodError",
    "JobNotFoundError",
    "RunAlreadyActiveError",
    "RunTakenOverError",
    "ScrapeCrashedError",
    "ScrapeInterruptedError",
]


class JobNotFoundError(Exception):
    def __init__(self, job_id: int) -> None:
        super().__init__(f"job {job_id} not found")
        self.job_id = job_id


class CollectionRunNotFoundError(Exception):
    def __init__(self, run_id: int) -> None:
        super().__init__(f"collection run {run_id} not found")
        self.run_id = run_id


class InvalidPeriodError(Exception):
    """`seen_from` is after `seen_to` (rule 21)."""

    def __init__(self, seen_from: date, seen_to: date) -> None:
        super().__init__(
            f"seen_from {seen_from.isoformat()} is after seen_to {seen_to.isoformat()}"
        )
        self.seen_from = seen_from
        self.seen_to = seen_to
