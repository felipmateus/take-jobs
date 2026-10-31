"""Domain errors carry their context; ports stay structurally implementable by plain fakes."""

from collections.abc import Sequence
from datetime import UTC, datetime

from take_jobs.domain import ports
from take_jobs.domain.errors import (
    RunAlreadyActiveError,
    RunTakenOverError,
    ScrapeCrashedError,
    ScrapeInterruptedError,
)
from take_jobs.domain.models import ScrapeReport


def test_run_already_active_error_carries_run_id_and_start() -> None:
    started_at = datetime(2026, 10, 30, 9, 0, tzinfo=UTC)

    error = RunAlreadyActiveError(7, started_at)

    assert error.run_id == 7
    assert error.started_at == started_at
    assert "7" in str(error)
    assert "2026-10-30T09:00:00+00:00" in str(error)


def test_run_taken_over_error_carries_run_id() -> None:
    error = RunTakenOverError(1)

    assert error.run_id == 1
    assert "1" in str(error)


def test_scrape_errors_keep_their_message() -> None:
    assert str(ScrapeCrashedError("boom")) == "boom"
    assert isinstance(ScrapeInterruptedError("signal"), Exception)


class _FakeClock:
    def now(self) -> datetime:
        return datetime(2026, 10, 30, 12, 0, tzinfo=UTC)


class _FakeScraper:
    def __init__(self) -> None:
        self.interrupted = False

    def scrape(self, terms: Sequence[str]) -> ScrapeReport:
        return ScrapeReport(outcomes=())

    def interrupt(self) -> None:
        self.interrupted = True


def test_plain_classes_satisfy_the_clock_and_scraper_ports() -> None:
    clock: ports.Clock = _FakeClock()
    scraper: ports.JobScraper = _FakeScraper()

    assert clock.now().tzinfo is UTC
    assert scraper.scrape(["dev"]) == ScrapeReport(outcomes=())
    scraper.interrupt()
    assert scraper.interrupted is True  # type: ignore[attr-defined]


def test_ports_expose_the_contract_surface() -> None:
    assert {"upsert", "get", "search"} <= set(dir(ports.JobRepository))
    assert {"is_empty", "ping"} <= set(dir(ports.JobStoreProbe))
    assert {
        "start",
        "get_active",
        "latest_finished",
        "mark_interrupted",
        "finish",
        "get",
        "list",
    } <= set(dir(ports.CollectionRunRepository))
    assert {"jobs", "runs", "probe"} <= set(ports.UnitOfWork.__annotations__)
    assert {"scrape", "interrupt"} <= set(dir(ports.JobScraper))
