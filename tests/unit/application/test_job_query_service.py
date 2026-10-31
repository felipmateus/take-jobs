"""UT-050 to UT-055: JobQueryService over in-memory fakes."""

from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from take_jobs.application.errors import InvalidPeriodError, JobNotFoundError
from take_jobs.application.queries import JobQuery, JobView
from take_jobs.application.services import JobQueryService
from take_jobs.domain.models import ScrapedJob, Seniority
from tests.fakes import NOW, FixedClock, InMemoryJobRepository, InMemoryStore

SAO_PAULO = ZoneInfo("America/Sao_Paulo")
UTC_ZONE = ZoneInfo("UTC")


def make_service(
    store: InMemoryStore | None = None,
    *,
    inactive_after: timedelta = timedelta(days=7),
    tz: ZoneInfo = UTC_ZONE,
) -> tuple[JobQueryService, InMemoryJobRepository]:
    repo = InMemoryJobRepository(store or InMemoryStore())
    return JobQueryService(repo, FixedClock(NOW), inactive_after, tz), repo


def scraped(external_id: str = "1", title: str = "Desenvolvedor Python") -> ScrapedJob:
    return ScrapedJob(
        source="vagas",
        external_id=external_id,
        title=title,
        url=f"https://example.test/{external_id}",
        company="Acme",
        location="Sao Paulo",
        description=None,
        published_label=None,
    )


@pytest.mark.parametrize(
    ("inactive_after", "expected"),
    [
        (timedelta(days=7), datetime(2026, 10, 23, 12, tzinfo=UTC)),
        (timedelta(days=3), datetime(2026, 10, 27, 12, tzinfo=UTC)),
    ],
)
async def test_ut050_default_search_applies_the_activity_cutoff(
    inactive_after: timedelta, expected: datetime
) -> None:
    service, repo = make_service(inactive_after=inactive_after)

    await service.search(JobQuery())

    (criteria,) = repo.searches
    assert criteria.active_since == expected
    assert (criteria.page, criteria.size) == (1, 20)


async def test_ut051_include_inactive_drops_the_cutoff() -> None:
    service, repo = make_service()

    await service.search(JobQuery(include_inactive=True))

    assert repo.searches[0].active_since is None


async def test_ut052_inverted_period_is_rejected_before_searching() -> None:
    service, repo = make_service()

    with pytest.raises(InvalidPeriodError) as raised:
        await service.search(JobQuery(seen_from=date(2026, 10, 20), seen_to=date(2026, 10, 1)))

    assert raised.value.seen_from == date(2026, 10, 20)
    assert repo.searches == []


async def test_ut052_same_day_period_is_valid() -> None:
    service, repo = make_service()

    await service.search(JobQuery(seen_from=date(2026, 10, 5), seen_to=date(2026, 10, 5)))

    assert repo.searches[0].seen_from < repo.searches[0].seen_to


async def test_ut053_period_bounds_follow_the_configured_time_zone() -> None:
    service, repo = make_service(tz=SAO_PAULO)

    await service.search(JobQuery(seen_from=date(2026, 10, 1), seen_to=date(2026, 10, 15)))

    criteria = repo.searches[0]
    assert criteria.seen_from == datetime(2026, 10, 1, 3, 0, tzinfo=UTC)
    assert criteria.seen_to == datetime(2026, 10, 16, 2, 59, 59, 999999, tzinfo=UTC)


async def test_ut053_only_one_bound_leaves_the_other_open() -> None:
    service, repo = make_service(tz=SAO_PAULO)

    await service.search(JobQuery(seen_from=date(2026, 10, 1)))
    await service.search(JobQuery(seen_to=date(2026, 10, 15)))

    assert repo.searches[0].seen_to is None
    assert repo.searches[1].seen_from is None


async def test_ut054_blank_text_and_location_are_ignored() -> None:
    service, repo = make_service()

    await service.search(JobQuery(q="   ", location=""))

    assert repo.searches[0].text is None
    assert repo.searches[0].location is None


async def test_ut054_text_and_location_are_stripped_and_filters_forwarded() -> None:
    service, repo = make_service()

    await service.search(
        JobQuery(
            q="  python ",
            location=" Recife ",
            sources=frozenset({"vagas"}),
            seniorities=frozenset({Seniority.SENIOR}),
            page=3,
            size=50,
        )
    )

    criteria = repo.searches[0]
    assert (criteria.text, criteria.location) == ("python", "Recife")
    assert criteria.sources == frozenset({"vagas"})
    assert criteria.seniorities == frozenset({Seniority.SENIOR})
    assert (criteria.page, criteria.size) == (3, 50)


async def test_search_returns_job_views_with_computed_activity() -> None:
    store = InMemoryStore()
    store.add_job(scraped("1"), seen_at=NOW - timedelta(days=1))
    store.add_job(scraped("2"), seen_at=NOW - timedelta(days=10))
    service, _ = make_service(store)

    page = await service.search(JobQuery(include_inactive=True))

    assert [(view.external_id, view.active) for view in page.items] == [("1", True), ("2", False)]
    assert (page.total, page.page, page.size) == (2, 1, 20)


async def test_activity_boundary_is_inclusive() -> None:
    store = InMemoryStore()
    stored = store.add_job(scraped(), seen_at=NOW - timedelta(days=7))
    service, _ = make_service(store)

    assert (await service.get(stored.id)).active is True


async def test_ut055_unknown_job_raises_not_found() -> None:
    service, _ = make_service()

    with pytest.raises(JobNotFoundError) as raised:
        await service.get(999)

    assert raised.value.job_id == 999


async def test_ut055_inactive_job_is_still_returned_by_detail() -> None:
    store = InMemoryStore()
    stored = store.add_job(scraped(), seen_at=NOW - timedelta(days=10))
    service, _ = make_service(store)

    view = await service.get(stored.id)

    assert isinstance(view, JobView)
    assert view.active is False
    assert (view.id, view.title) == (stored.id, stored.title)
