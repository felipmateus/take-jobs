"""IT-002 to IT-006 and IT-010: the SQLAlchemy adapters against PostgreSQL 17."""

import socket
import time
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import and_, select, text
from sqlalchemy.dialects import postgresql
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from take_jobs.domain.errors import RunAlreadyActiveError, RunTakenOverError
from take_jobs.domain.models import (
    CombinationResult,
    JobSearchCriteria,
    ResultStatus,
    RunStatus,
    RunTotals,
    RunTrigger,
    Seniority,
)
from take_jobs.infrastructure.db import session as session_module
from take_jobs.infrastructure.db.job_repository import SqlAlchemyJobRepository, _conditions
from take_jobs.infrastructure.db.models import JobRow
from take_jobs.infrastructure.db.probe import SqlAlchemyJobStoreProbe
from take_jobs.infrastructure.db.run_repository import SqlAlchemyCollectionRunRepository
from take_jobs.infrastructure.db.session import make_engine, make_sessionmaker
from take_jobs.infrastructure.db.uow import SqlAlchemyUnitOfWork
from tests.support.database import scraped_job


def at(month: int, day: int, hour: int = 12) -> datetime:
    return datetime(2026, month, day, hour, tzinfo=UTC)


@pytest.fixture
def jobs(session: AsyncSession) -> SqlAlchemyJobRepository:
    return SqlAlchemyJobRepository(session)


@pytest.fixture
def runs(session: AsyncSession) -> SqlAlchemyCollectionRunRepository:
    return SqlAlchemyCollectionRunRepository(session)


def external_ids(page) -> set[str]:
    return {job.external_id for job in page.items}


# --------------------------------------------------------------------------- IT-002


async def test_upsert_inserts_then_refreshes_keeping_first_seen(jobs) -> None:
    t1, t2 = at(10, 1), at(10, 5)
    created = scraped_job("100", company=None, description=None, published_label=None)

    assert await jobs.upsert(created, Seniority.JUNIOR, t1) is True
    page = await jobs.search(JobSearchCriteria())
    (stored,) = page.items
    assert (stored.source, stored.external_id) == ("vagas", "100")
    assert stored.title == "Desenvolvedor Python"
    assert stored.url == "https://example.test/vagas/100"
    assert stored.location == "São Paulo - SP"
    assert stored.company is None
    assert stored.description is None
    assert stored.published_label is None
    assert stored.seniority is Seniority.JUNIOR
    assert stored.first_seen_at == stored.last_seen_at == t1

    refreshed = scraped_job("100", title="Desenvolvedor Python Sênior", company="Nova")
    assert await jobs.upsert(refreshed, Seniority.SENIOR, t2) is False
    page = await jobs.search(JobSearchCriteria())
    (stored,) = page.items
    assert page.total == 1
    assert stored.title == "Desenvolvedor Python Sênior"
    assert stored.company == "Nova"
    assert stored.seniority is Seniority.SENIOR
    assert stored.first_seen_at == t1
    assert stored.last_seen_at == t2
    assert await jobs.get(stored.id) == stored


async def test_upsert_with_no_seniority_clears_it(jobs) -> None:
    await jobs.upsert(scraped_job("1"), Seniority.MID, at(10, 1))
    await jobs.upsert(scraped_job("1"), None, at(10, 2))
    (stored,) = (await jobs.search(JobSearchCriteria())).items
    assert stored.seniority is None


async def test_same_external_id_on_another_source_is_another_job(jobs) -> None:
    assert await jobs.upsert(scraped_job("100"), None, at(10, 1)) is True
    assert await jobs.upsert(scraped_job("100", source="infojobs"), None, at(10, 1)) is True
    page = await jobs.search(JobSearchCriteria())
    assert page.total == 2
    assert {job.source for job in page.items} == {"vagas", "infojobs"}


async def test_get_returns_none_for_an_unknown_id(jobs) -> None:
    assert await jobs.get(987654) is None


async def test_upsert_then_get_in_one_session_sees_the_refresh(jobs) -> None:
    await jobs.upsert(scraped_job("1", title="Old"), None, at(10, 1))
    (first,) = (await jobs.search(JobSearchCriteria())).items
    await jobs.upsert(scraped_job("1", title="New"), None, at(10, 2))
    refreshed = await jobs.get(first.id)
    assert refreshed is not None
    assert refreshed.title == "New"
    assert refreshed.last_seen_at == at(10, 2)


# --------------------------------------------------------------------------- IT-003


@pytest.fixture
async def search_jobs(jobs) -> SqlAlchemyJobRepository:
    seen = at(10, 1)
    for job in (
        scraped_job("py", title="Desenvolvedor Python", company="Acme", description=None),
        scraped_job("bf", title="Analista", company="Bom Futuro", description=None),
        scraped_job("mig", title="Engenheiro", company="Acme", description="migração de ETLs"),
        scraped_job("pct", title="Dados", company="Acme", description="aumento de 50% na carga"),
        scraped_job("pct2", title="Dados", company="Acme", description="aumento de 5000 na carga"),
        scraped_job("ab", title="Dados", company="Acme", description="campo a_b exportado"),
        scraped_job("ab2", title="Dados", company="Acme", description="campo axb exportado"),
        scraped_job("bs", title="Dados", company="Acme", description=r"caminho c:\temp"),
        scraped_job("rust", title="Desenvolvedor Rust", company=None, description=None),
    ):
        await jobs.upsert(job, None, seen)
    return jobs


@pytest.mark.parametrize(
    ("q", "expected"),
    [
        pytest.param("python", {"py"}, id="title"),
        pytest.param("PYTHON", {"py"}, id="case"),
        pytest.param("bom futuro", {"bf"}, id="company"),
        pytest.param("MIGRACAO", {"mig"}, id="accent-in-text-only"),
        pytest.param("migração", {"mig"}, id="accent-in-query"),
        pytest.param("50%", {"pct"}, id="percent-literal"),
        pytest.param("%", {"pct"}, id="lone-percent"),
        pytest.param("a_b", {"ab"}, id="underscore-literal"),
        pytest.param("_", {"ab"}, id="lone-underscore"),
        pytest.param("c:\\temp", {"bs"}, id="backslash-literal"),
        pytest.param("kotlin", set(), id="no-match"),
        pytest.param("rust", {"rust"}, id="null-company-and-description"),
        pytest.param("pyth", {"py"}, id="substring"),
    ],
)
async def test_text_search(search_jobs, q: str, expected: set[str]) -> None:
    page = await search_jobs.search(JobSearchCriteria(text=q))
    assert external_ids(page) == expected
    assert page.total == len(expected)


async def test_a_search_without_match_returns_an_empty_page(search_jobs) -> None:
    page = await search_jobs.search(JobSearchCriteria(text="kotlin"))
    assert page.total == 0
    assert page.items == ()


async def test_location_search_is_literal_too(jobs) -> None:
    await jobs.upsert(scraped_job("1", location="Sao_Paulo"), None, at(10, 1))
    await jobs.upsert(scraped_job("2", location="SaoXPaulo"), None, at(10, 1))
    page = await jobs.search(JobSearchCriteria(location="o_p"))
    assert external_ids(page) == {"1"}


# --------------------------------------------------------------------------- IT-004

# key: (source, location, seniority, first seen, last seen). "Now" is 2026-10-30 12:00.
FILTER_JOBS = {
    "1": ("vagas", "São Paulo - SP", Seniority.SENIOR, at(9, 25), at(10, 2)),
    "2": ("vagas", "Rio de Janeiro - RJ", Seniority.MID, at(10, 16), at(10, 20)),
    "3": ("infojobs", "São Paulo - SP", Seniority.JUNIOR, at(10, 5), at(10, 10)),
    "4": ("infojobs", "Curitiba - PR", Seniority.INTERN, at(10, 1), at(10, 14)),
    "5": ("vagas", "Belo Horizonte - MG", Seniority.MID, at(10, 10), at(10, 22)),
    "6": ("infojobs", "Remoto", None, at(9, 1), at(9, 2)),
    "7": ("vagas", "São Paulo - SP", Seniority.SENIOR, at(10, 20), at(10, 30)),
    "8": ("infojobs", None, Seniority.MID, at(10, 28), at(10, 30)),
}
NOW = at(10, 30)
END_OF_DAY = timedelta(days=1) - timedelta(microseconds=1)


@pytest.fixture
async def filter_jobs(jobs) -> SqlAlchemyJobRepository:
    for key, (source, location, seniority, first, last) in FILTER_JOBS.items():
        await jobs.upsert(scraped_job(key, source=source, location=location), seniority, first)
        if last != first:
            await jobs.upsert(scraped_job(key, source=source, location=location), seniority, last)
    return jobs


def day(month: int, day_: int) -> datetime:
    return at(month, day_, 0)


FILTER_CASES = [
    pytest.param(JobSearchCriteria(), set("12345678"), id="no-filter"),
    pytest.param(JobSearchCriteria(sources=frozenset({"infojobs"})), set("3468"), id="one-source"),
    pytest.param(
        JobSearchCriteria(sources=frozenset({"infojobs", "vagas"})),
        set("12345678"),
        id="both-sources",
    ),
    pytest.param(JobSearchCriteria(location="sao paulo"), set("137"), id="location-accent"),
    pytest.param(JobSearchCriteria(location="CURITIBA"), {"4"}, id="location-case"),
    pytest.param(
        JobSearchCriteria(seniorities=frozenset({Seniority.SENIOR, Seniority.MID})),
        set("12578"),
        id="seniorities",
    ),
    pytest.param(
        JobSearchCriteria(seen_from=day(10, 1), seen_to=day(10, 15) + END_OF_DAY),
        set("1345"),
        id="period-overlap",
    ),
    pytest.param(
        JobSearchCriteria(seen_from=day(10, 16), seen_to=day(10, 16) + END_OF_DAY),
        {"2", "5"},
        id="period-one-day",
    ),
    pytest.param(JobSearchCriteria(seen_from=day(10, 25)), set("78"), id="period-open-end"),
    pytest.param(JobSearchCriteria(seen_to=day(10, 1) + END_OF_DAY), set("146"), id="period-open"),
    pytest.param(JobSearchCriteria(active_since=NOW - timedelta(days=7)), set("78"), id="active"),
    pytest.param(JobSearchCriteria(active_since=None), set("12345678"), id="inactive-included"),
    pytest.param(
        JobSearchCriteria(
            seen_from=day(10, 15),
            seen_to=day(10, 25) + END_OF_DAY,
            active_since=NOW - timedelta(days=7),
        ),
        {"7"},
        id="period-and-active",
    ),
    pytest.param(
        JobSearchCriteria(
            sources=frozenset({"vagas"}),
            location="sao paulo",
            seniorities=frozenset({Seniority.SENIOR}),
        ),
        {"1", "7"},
        id="all-and",
    ),
]


@pytest.mark.parametrize(("criteria", "expected"), FILTER_CASES)
async def test_filters(filter_jobs, criteria: JobSearchCriteria, expected: set[str]) -> None:
    page = await filter_jobs.search(criteria)
    assert external_ids(page) == expected
    assert page.total == len(expected)


@pytest.mark.parametrize(
    ("criteria", "index"),
    [
        pytest.param(JobSearchCriteria(text="python"), "ix_jobs_search_text_trgm", id="text"),
        pytest.param(
            JobSearchCriteria(location="sao paulo"), "ix_jobs_location_trgm", id="location"
        ),
    ],
)
async def test_text_filters_can_use_their_trigram_index(
    jobs, session: AsyncSession, criteria: JobSearchCriteria, index: str
) -> None:
    """The repository's expressions match the indexed expressions (ADR-005)."""
    for number in range(50):
        await jobs.upsert(scraped_job(str(number), title=f"Dev {number}"), None, at(10, 1))
    await session.execute(text("ANALYZE jobs"))
    await session.execute(text("SET LOCAL enable_seqscan = off"))
    statement = select(JobRow.id).where(and_(*_conditions(criteria)))
    sql = str(
        statement.compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True})
    )
    plan = "\n".join((await session.execute(text(f"EXPLAIN {sql}"))).scalars())
    assert index in plan


# --------------------------------------------------------------------------- IT-005


async def test_ordering_and_pagination(jobs, session: AsyncSession) -> None:
    # 45 jobs, three timestamps shared by groups so ties on every sort key occur.
    for number in range(45):
        group = number % 3
        await jobs.upsert(scraped_job(f"{number:02d}"), None, at(10, 1 + group))
        if number % 2:
            await jobs.upsert(scraped_job(f"{number:02d}"), None, at(10, 10 + group))
    await session.flush()

    expected = (
        await session.execute(
            text("SELECT id FROM jobs ORDER BY last_seen_at DESC, first_seen_at DESC, id DESC")
        )
    ).scalars()
    expected_ids = list(expected)
    assert len(expected_ids) == 45

    page1 = await jobs.search(JobSearchCriteria(page=1, size=20))
    page2 = await jobs.search(JobSearchCriteria(page=2, size=20))
    page3 = await jobs.search(JobSearchCriteria(page=3, size=20))
    page4 = await jobs.search(JobSearchCriteria(page=4, size=20))

    assert [job.id for job in page1.items] == expected_ids[:20]
    assert [job.id for job in page2.items] == expected_ids[20:40]
    assert [job.id for job in page3.items] == expected_ids[40:]
    assert len(page3.items) == 5
    assert page4.items == ()
    assert page4.total == 45
    assert (page1.total, page2.total, page3.total) == (45, 45, 45)
    assert page1.pages == 3

    # The order itself: recency, then first seen, then id, all descending.
    ordered = [*page1.items, *page2.items, *page3.items]
    keys = [(job.last_seen_at, job.first_seen_at, job.id) for job in ordered]
    assert keys == sorted(keys, reverse=True)
    assert len({(job.last_seen_at, job.first_seen_at) for job in ordered}) < 45


# --------------------------------------------------------------------------- IT-006


def result(source: str, term: str, new: int, seen: int, disc: int, **kw) -> CombinationResult:
    return CombinationResult(
        source=source,
        term=term,
        status=kw.get("status", ResultStatus.SUCCESS),
        pages=kw.get("pages", 1),
        new=new,
        seen_again=seen,
        discarded=disc,
        error=kw.get("error"),
    )


async def test_start_creates_a_running_run_and_a_second_start_is_refused(runs, session) -> None:
    started = at(10, 1)
    run_id = await runs.start(RunTrigger.MANUAL, started, 4)
    await session.commit()

    active = await runs.get_active()
    assert active is not None
    assert (active.id, active.status, active.trigger) == (
        run_id,
        RunStatus.RUNNING,
        RunTrigger.MANUAL,
    )
    assert active.expected_combinations == 4
    assert active.started_at == started

    with pytest.raises(RunAlreadyActiveError) as raised:
        await runs.start(RunTrigger.SCHEDULED, at(10, 2), 4)
    assert raised.value.run_id == run_id
    assert raised.value.started_at == started
    await session.rollback()
    assert (await runs.list(1, 20)).total == 1


async def test_a_second_connection_is_refused_by_the_database(
    sessionmaker: async_sessionmaker[AsyncSession],
) -> None:
    async with SqlAlchemyUnitOfWork(sessionmaker) as first:
        run_id = await first.runs.start(RunTrigger.STARTUP, at(10, 1), 2)
    with pytest.raises(RunAlreadyActiveError) as raised:
        async with SqlAlchemyUnitOfWork(sessionmaker) as second:
            await second.runs.start(RunTrigger.MANUAL, at(10, 2), 2)
    assert raised.value.run_id == run_id


async def test_finish_stores_results_and_only_once(runs, session) -> None:
    run_id = await runs.start(RunTrigger.SCHEDULED, at(10, 1), 2)
    results = [
        result("vagas", "python", 3, 1, 2, pages=2),
        result("infojobs", "python", 0, 4, 1, status=ResultStatus.FAILED, error="timeout"),
    ]
    await runs.finish(run_id, RunStatus.PARTIAL, results, at(10, 1, 13), None)
    await session.commit()

    run = await runs.get(run_id)
    assert run is not None
    assert run.status is RunStatus.PARTIAL
    assert run.finished_at == at(10, 1, 13)
    assert run.error is None
    assert run.results == tuple(results)
    assert await runs.get_active() is None

    with pytest.raises(RunTakenOverError) as raised:
        await runs.finish(
            run_id, RunStatus.SUCCESS, [result("vagas", "go", 1, 0, 0)], at(10, 2), None
        )
    assert raised.value.run_id == run_id
    after = await runs.get(run_id)
    assert after == run  # the failed second finish wrote nothing


async def test_finish_and_mark_interrupted_raise_for_a_run_that_is_not_running(
    runs, session
) -> None:
    run_id = await runs.start(RunTrigger.MANUAL, at(10, 1), 1)
    await runs.mark_interrupted(run_id, at(10, 1, 13))
    await session.commit()

    run = await runs.get(run_id)
    assert run is not None
    assert (run.status, run.error, run.finished_at) == (
        RunStatus.FAILED,
        "interrupted",
        at(10, 1, 13),
    )

    with pytest.raises(RunTakenOverError):
        await runs.mark_interrupted(run_id, at(10, 2))
    with pytest.raises(RunTakenOverError):
        await runs.finish(run_id, RunStatus.FAILED, [], at(10, 2), "ingest failed: boom")
    with pytest.raises(RunTakenOverError):
        await runs.finish(987654, RunStatus.FAILED, [], at(10, 2), "x")
    assert await runs.get(run_id) == run


async def test_finish_records_a_run_level_error(runs, session) -> None:
    run_id = await runs.start(RunTrigger.MANUAL, at(10, 1), 1)
    await runs.finish(run_id, RunStatus.FAILED, [], at(10, 1, 13), "interrupted by signal")
    run = await runs.get(run_id)
    assert run is not None
    assert (run.status, run.error, run.results) == (RunStatus.FAILED, "interrupted by signal", ())
    assert run.totals == RunTotals(0, 0, 0)


async def test_finish_refuses_a_running_status(runs, session) -> None:
    run_id = await runs.start(RunTrigger.MANUAL, at(10, 1), 1)
    with pytest.raises(ValueError, match="final status"):
        await runs.finish(run_id, RunStatus.RUNNING, [], at(10, 2), None)


async def test_a_running_run_has_no_results_and_no_finish_time(runs, session) -> None:
    run_id = await runs.start(RunTrigger.MANUAL, at(10, 1), 3)
    run = await runs.get(run_id)
    assert run is not None
    assert run.results == ()
    assert run.finished_at is None
    assert run.totals == RunTotals(0, 0, 0)
    page = await runs.list(1, 20)
    assert [item.id for item in page.items] == [run_id]
    assert page.items[0].status is RunStatus.RUNNING


async def test_get_an_unknown_run_is_none(runs) -> None:
    assert await runs.get(987654) is None


async def test_list_on_an_empty_table(runs) -> None:
    page = await runs.list(1, 20)
    assert (page.items, page.total, page.pages) == ((), 0, 0)
    assert await runs.get_active() is None
    assert await runs.latest_finished() is None


async def test_list_orders_by_start_desc_and_paginates(runs, session) -> None:
    ids = []
    for day_ in (3, 1, 2, 4, 5):  # inserted out of order on purpose
        run_id = await runs.start(RunTrigger.SCHEDULED, at(10, day_), 1)
        await runs.finish(run_id, RunStatus.SUCCESS, [], at(10, day_, 13), None)
        ids.append((day_, run_id))
    by_start = [run_id for _, run_id in sorted(ids, reverse=True)]

    first = await runs.list(1, 2)
    second = await runs.list(2, 2)
    third = await runs.list(3, 2)
    beyond = await runs.list(4, 2)
    assert [r.id for r in first.items] == by_start[:2]
    assert [r.id for r in second.items] == by_start[2:4]
    assert [r.id for r in third.items] == by_start[4:]
    assert beyond.items == ()
    assert (first.total, first.pages, beyond.total) == (5, 3, 5)


async def test_list_carries_totals_and_get_carries_totals_and_results(runs, session) -> None:
    run_id = await runs.start(RunTrigger.SCHEDULED, at(10, 1), 2)
    results = [result("vagas", "python", 3, 1, 2), result("infojobs", "python", 0, 4, 1)]
    await runs.finish(run_id, RunStatus.SUCCESS, results, at(10, 1, 13), None)
    other = await runs.start(RunTrigger.MANUAL, at(10, 2), 1)
    await runs.finish(other, RunStatus.FAILED, [], at(10, 2, 13), "boom")

    page = await runs.list(1, 20)
    listed = {item.id: item for item in page.items}
    assert listed[run_id].totals == RunTotals(3, 5, 3)
    assert listed[run_id].results == ()
    assert listed[other].totals == RunTotals(0, 0, 0)

    detail = await runs.get(run_id)
    assert detail is not None
    assert detail.totals == RunTotals(3, 5, 3)
    assert detail.results == tuple(results)


async def test_latest_finished_ignores_the_running_run(runs, session) -> None:
    old = await runs.start(RunTrigger.SCHEDULED, at(10, 1), 1)
    await runs.finish(old, RunStatus.SUCCESS, [], at(10, 1, 13), None)
    newer = await runs.start(RunTrigger.SCHEDULED, at(10, 3), 1)
    await runs.finish(newer, RunStatus.FAILED, [], at(10, 3, 13), "boom")
    middle = await runs.start(RunTrigger.MANUAL, at(10, 2), 1)
    await runs.finish(middle, RunStatus.PARTIAL, [], at(10, 2, 13), None)
    running = await runs.start(RunTrigger.MANUAL, at(10, 9), 1)

    latest = await runs.latest_finished()
    assert latest is not None
    assert latest.id == newer
    assert latest.id != running
    assert latest.status is RunStatus.FAILED

    await runs.finish(running, RunStatus.SUCCESS, [], at(10, 9, 13), None)
    latest = await runs.latest_finished()
    assert latest is not None
    assert latest.id == running


# --------------------------------------------------------------------------- UoW


async def test_unit_of_work_commits_on_success(sessionmaker) -> None:
    async with SqlAlchemyUnitOfWork(sessionmaker) as uow:
        await uow.jobs.upsert(scraped_job("1"), None, at(10, 1))
        run_id = await uow.runs.start(RunTrigger.MANUAL, at(10, 1), 1)
        assert await uow.probe.is_empty() is False

    async with SqlAlchemyUnitOfWork(sessionmaker) as uow:
        assert (await uow.jobs.search(JobSearchCriteria())).total == 1
        assert (await uow.runs.get_active()).id == run_id


async def test_unit_of_work_rolls_back_on_error(sessionmaker) -> None:
    async def work_that_fails() -> None:
        async with SqlAlchemyUnitOfWork(sessionmaker) as uow:
            await uow.jobs.upsert(scraped_job("1"), None, at(10, 1))
            await uow.runs.start(RunTrigger.MANUAL, at(10, 1), 1)
            raise RuntimeError("boom")

    with pytest.raises(RuntimeError, match="boom"):
        await work_that_fails()

    async with SqlAlchemyUnitOfWork(sessionmaker) as uow:
        assert await uow.probe.is_empty() is True
        assert await uow.runs.get_active() is None


async def test_failed_finish_rolls_back_the_results_with_the_unit_of_work(sessionmaker) -> None:
    async with SqlAlchemyUnitOfWork(sessionmaker) as uow:
        run_id = await uow.runs.start(RunTrigger.MANUAL, at(10, 1), 1)

    async def finish_then_fail() -> None:
        async with SqlAlchemyUnitOfWork(sessionmaker) as uow:
            await uow.runs.finish(
                run_id, RunStatus.SUCCESS, [result("vagas", "go", 1, 0, 0)], at(10, 2), None
            )
            raise RuntimeError("after finish")

    with pytest.raises(RuntimeError, match="after finish"):
        await finish_then_fail()
    async with SqlAlchemyUnitOfWork(sessionmaker) as uow:
        run = await uow.runs.get(run_id)
        assert run is not None
        assert run.status is RunStatus.RUNNING
        assert run.results == ()


# --------------------------------------------------------------------------- IT-010


async def test_probe_is_empty_and_ping(jobs, session: AsyncSession) -> None:
    probe = SqlAlchemyJobStoreProbe(session)
    assert await probe.is_empty() is True
    await jobs.upsert(scraped_job("1"), None, at(10, 1))
    assert await probe.is_empty() is False
    await probe.ping()


async def test_ping_on_a_closed_port_fails_within_three_seconds() -> None:
    with socket.socket() as holder:
        holder.bind(("127.0.0.1", 0))
        port = holder.getsockname()[1]
    engine = make_engine(f"postgresql+asyncpg://u:take_jobs_dev@127.0.0.1:{port}/db")
    try:
        async with make_sessionmaker(engine)() as session:
            started = time.monotonic()
            with pytest.raises((OSError, DBAPIError)):
                await SqlAlchemyJobStoreProbe(session).ping()
            elapsed = time.monotonic() - started
    finally:
        await engine.dispose()
    assert elapsed < 3


def test_make_engine_sets_a_five_second_connect_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict = {}

    def fake_create_async_engine(url: str, **kwargs: object) -> object:
        captured.update(kwargs)
        return object()

    monkeypatch.setattr(session_module, "create_async_engine", fake_create_async_engine)
    make_engine("postgresql+asyncpg://u:take_jobs_dev@127.0.0.1:1/db")
    assert captured["connect_args"]["timeout"] == 5


async def test_make_engine_forces_custom_plans(database_url: str) -> None:
    """Without it a generic plan, chosen after five executions of a prepared statement, makes
    1-2 character searches 3-4x slower (see IT-011)."""
    engine = make_engine(database_url)
    try:
        async with engine.connect() as connection:
            mode = await connection.scalar(text("SHOW plan_cache_mode"))
    finally:
        await engine.dispose()
    assert mode == "force_custom_plan"
