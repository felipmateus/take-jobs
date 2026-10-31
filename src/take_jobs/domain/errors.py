"""Domain errors raised by ports (stdlib only)."""

from datetime import datetime


class RunAlreadyActiveError(Exception):
    """A start attempt found another run in `running` (rule 13)."""

    def __init__(self, run_id: int, started_at: datetime) -> None:
        super().__init__(
            f"collection run {run_id} is already running since {started_at.isoformat()}"
        )
        self.run_id = run_id
        self.started_at = started_at


class RunTakenOverError(Exception):
    """A conditional update on a `running` run affected no row: the run already left `running`."""

    def __init__(self, run_id: int) -> None:
        super().__init__(f"collection run {run_id} is no longer running")
        self.run_id = run_id


class ScrapeInterruptedError(Exception):
    """A signal stopped the crawl (rule 24)."""


class ScrapeCrashedError(Exception):
    """The crawl ended without a report."""
