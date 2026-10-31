"""UT-014, UT-016, UT-017: model behaviour."""

from dataclasses import FrozenInstanceError
from datetime import UTC, datetime, timedelta

import pytest

from take_jobs.domain.models import CombinationResult, Job, Page, ResultStatus, RunTotals

NOW = datetime(2026, 10, 30, 12, 0, tzinfo=UTC)


def _job(last_seen_at: datetime) -> Job:
    return Job(
        id=1,
        source="vagas",
        external_id="42",
        title="Dev",
        url="https://example.test/1",
        company=None,
        location=None,
        description=None,
        published_label=None,
        seniority=None,
        first_seen_at=last_seen_at,
        last_seen_at=last_seen_at,
    )


def test_ut014_job_active_at_exactly_the_limit() -> None:
    inactive_after = timedelta(days=7)

    assert _job(NOW - timedelta(days=7)).is_active(NOW, inactive_after) is True
    assert _job(NOW - timedelta(days=7, seconds=1)).is_active(NOW, inactive_after) is False
    assert _job(NOW).is_active(NOW, inactive_after) is True


def test_job_is_immutable() -> None:
    job = _job(NOW)

    with pytest.raises(FrozenInstanceError):
        job.title = "other"  # type: ignore[misc]


def test_ut016_page_count() -> None:
    assert Page(items=(), total=0, page=1, size=20).pages == 0
    assert Page(items=(), total=41, page=1, size=20).pages == 3
    assert Page(items=(), total=40, page=1, size=20).pages == 2
    beyond_last = Page(items=(), total=41, page=5, size=20)
    assert beyond_last.pages == 3
    assert beyond_last.page == 5


def _combination(new: int, seen_again: int, discarded: int) -> CombinationResult:
    return CombinationResult(
        source="vagas",
        term="dev",
        status=ResultStatus.SUCCESS,
        pages=1,
        new=new,
        seen_again=seen_again,
        discarded=discarded,
        error=None,
    )


def test_ut017_run_totals_sum_results() -> None:
    totals = RunTotals.from_results([_combination(3, 1, 2), _combination(0, 4, 1)])

    assert totals == RunTotals(new=3, seen_again=5, discarded=3)


def test_ut017_run_totals_of_no_results_are_zero() -> None:
    assert RunTotals.from_results([]) == RunTotals(new=0, seen_again=0, discarded=0)
