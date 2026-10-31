"""The dependency chain (`_spec.md` > API Endpoints). Everything comes from `request.app.state`,
set by `create_app`, so `create_app(settings=...)` governs every dependency and the lifespan
engine. This module and `app` are the only API modules that import infrastructure (ADR-001)."""

from collections.abc import AsyncIterator, Mapping
from datetime import timedelta
from typing import Annotated
from zoneinfo import ZoneInfo

from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from take_jobs.application.services import CollectionRunQueryService, JobQueryService
from take_jobs.config import Settings
from take_jobs.domain.ports import Clock, JobStoreProbe
from take_jobs.infrastructure.clock import SystemClock
from take_jobs.infrastructure.db.job_repository import SqlAlchemyJobRepository
from take_jobs.infrastructure.db.probe import SqlAlchemyJobStoreProbe
from take_jobs.infrastructure.db.run_repository import SqlAlchemyCollectionRunRepository
from take_jobs.infrastructure.scraping.registry import SourceDefinition


def get_settings(request: Request) -> Settings:
    return request.app.state.settings


def get_sources(request: Request) -> Mapping[str, SourceDefinition]:
    return request.app.state.sources


def get_sessionmaker(request: Request) -> async_sessionmaker[AsyncSession]:
    return request.app.state.sessionmaker


async def get_session(
    sessionmaker: Annotated[async_sessionmaker[AsyncSession], Depends(get_sessionmaker)],
) -> AsyncIterator[AsyncSession]:
    """One session per request; the API only reads, so closing it rolls everything back."""
    async with sessionmaker() as session:
        yield session


def get_clock() -> Clock:
    return SystemClock()


def get_job_query_service(
    session: Annotated[AsyncSession, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
    clock: Annotated[Clock, Depends(get_clock)],
) -> JobQueryService:
    return JobQueryService(
        SqlAlchemyJobRepository(session),
        clock,
        timedelta(days=settings.job_inactive_after_days),
        ZoneInfo(settings.scrape_timezone),
    )


def get_run_query_service(
    session: Annotated[AsyncSession, Depends(get_session)],
) -> CollectionRunQueryService:
    return CollectionRunQueryService(SqlAlchemyCollectionRunRepository(session))


def get_job_store_probe(session: Annotated[AsyncSession, Depends(get_session)]) -> JobStoreProbe:
    return SqlAlchemyJobStoreProbe(session)
