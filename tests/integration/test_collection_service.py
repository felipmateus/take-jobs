"""IT-008: atomic completion against PostgreSQL, then the `ingest failed` record."""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from take_jobs.application.services import CollectionService
from take_jobs.domain.models import (
    CombinationOutcome,
    RunStatus,
    RunTrigger,
    ScrapeReport,
)
from take_jobs.domain.rules import RelevancePolicy
from take_jobs.infrastructure.db.models import JobRow
from take_jobs.infrastructure.db.run_repository import SqlAlchemyCollectionRunRepository
from take_jobs.infrastructure.db.uow import SqlAlchemyUnitOfWork
from tests.fakes import FixedClock
from tests.support.database import scraped_job

NOW = datetime(2026, 10, 30, 12, 0, tzinfo=UTC)


@pytest.fixture
def service(sessionmaker: async_sessionmaker[AsyncSession]) -> CollectionService:
    return CollectionService(
        lambda: SqlAlchemyUnitOfWork(sessionmaker),
        RelevancePolicy(include=["desenvolvedor"], exclude=[]),
        FixedClock(NOW),
        run_timeout=timedelta(minutes=60),
    )


async def test_it008_failed_finish_stores_nothing_and_fail_run_records_the_error(
    service: CollectionService,
    sessionmaker: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run_id = await service.start_run(RunTrigger.MANUAL, expected_combinations=1)
    report = ScrapeReport(
        outcomes=(
            CombinationOutcome(
                source="vagas",
                term="desenvolvedor",
                jobs=tuple(scraped_job(str(n), title=f"Desenvolvedor {n}") for n in (1, 2, 3)),
                pages=1,
                error=None,
            ),
        )
    )

    async def broken_finish(*args: object, **kwargs: object) -> None:
        raise RuntimeError("db gone")

    monkeypatch.setattr(SqlAlchemyCollectionRunRepository, "finish", broken_finish)
    with pytest.raises(RuntimeError, match="db gone"):
        await service.complete_run(run_id, report)
    monkeypatch.undo()

    async with sessionmaker() as session:
        assert await session.scalar(select(func.count()).select_from(JobRow)) == 0
        assert await session.scalar(text("SELECT count(*) FROM collection_run_results")) == 0

    failed = await service.fail_run(run_id, "ingest failed: RuntimeError: db gone")

    assert (failed.status, failed.error, failed.results) == (
        RunStatus.FAILED,
        "ingest failed: RuntimeError: db gone",
        (),
    )
    reread = await service.get_run(run_id)
    assert reread is not None
    assert (reread.status, reread.error) == (
        RunStatus.FAILED,
        "ingest failed: RuntimeError: db gone",
    )
    async with sessionmaker() as session:
        assert await session.scalar(select(func.count()).select_from(JobRow)) == 0
        assert await session.scalar(text("SELECT count(*) FROM collection_run_results")) == 0


async def test_complete_run_commits_jobs_results_and_status_together(
    service: CollectionService, sessionmaker: async_sessionmaker[AsyncSession]
) -> None:
    run_id = await service.start_run(RunTrigger.MANUAL, expected_combinations=1)
    report = ScrapeReport(
        outcomes=(
            CombinationOutcome(
                source="vagas",
                term="desenvolvedor",
                jobs=(
                    scraped_job("1", title="Desenvolvedor Senior"),
                    scraped_job("2", title="Cozinheiro"),
                ),
                pages=1,
                error=None,
            ),
        )
    )
    hooks: list[str] = []

    run = await service.complete_run(run_id, report, before_commit=lambda: hooks.append("hook"))

    assert hooks == ["hook"]
    assert run.status is RunStatus.SUCCESS
    reread = await service.get_run(run_id)
    assert reread is not None
    assert (reread.status, reread.totals.new, reread.totals.discarded) == (RunStatus.SUCCESS, 1, 1)
    assert [(r.new, r.discarded) for r in reread.results] == [(1, 1)]
    async with sessionmaker() as session:
        assert await session.scalar(select(func.count()).select_from(JobRow)) == 1
