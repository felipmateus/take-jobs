"""Composition of the process commands: `CliDeps` and `build_cli_deps` (re-exported by `cli.main`).

`open_collection_service` builds and disposes a fresh engine on every call (Safety Invariant 5):
each `asyncio.run` in the collector gets its own connections, with a 5-second connect timeout.
"""

import time
from collections.abc import AsyncIterator, Callable, Mapping
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from dataclasses import dataclass
from datetime import timedelta

from apscheduler.schedulers.base import BaseScheduler
from apscheduler.schedulers.blocking import BlockingScheduler

from take_jobs.application.services import CollectionService
from take_jobs.cli.runner import CollectionRunner, SubprocessCollectionRunner
from take_jobs.config import Settings
from take_jobs.domain.ports import Clock, JobScraper
from take_jobs.domain.rules import RelevancePolicy
from take_jobs.infrastructure.clock import SystemClock
from take_jobs.infrastructure.db.session import make_engine, make_sessionmaker
from take_jobs.infrastructure.db.uow import SqlAlchemyUnitOfWork
from take_jobs.infrastructure.scraping.registry import SOURCES, SourceDefinition
from take_jobs.infrastructure.scraping.scraper import ScrapyJobScraper


@dataclass(frozen=True)
class CliDeps:
    settings: Settings
    sources: Mapping[str, SourceDefinition]
    relevance: RelevancePolicy  # built from settings; observable for UT-077
    scraper: JobScraper  # ScrapyJobScraper(sources, settings) by default
    open_collection_service: Callable[[], AbstractAsyncContextManager[CollectionService]]
    clock: Clock  # SystemClock by default
    runner: CollectionRunner  # scheduler only: Popen of `python -m take_jobs collect`
    sleep: Callable[[float], None]  # scheduler probe backoff; time.sleep by default
    scheduler_factory: Callable[[], BaseScheduler]  # BlockingScheduler by default


def _make_open_collection_service(
    settings: Settings, relevance: RelevancePolicy, clock: Clock
) -> Callable[[], AbstractAsyncContextManager[CollectionService]]:
    run_timeout = timedelta(minutes=settings.scrape_run_timeout_minutes)

    @asynccontextmanager
    async def open_collection_service() -> AsyncIterator[CollectionService]:
        engine = make_engine(settings.database_url)
        try:
            sessionmaker = make_sessionmaker(engine)
            yield CollectionService(
                lambda: SqlAlchemyUnitOfWork(sessionmaker), relevance, clock, run_timeout
            )
        finally:
            await engine.dispose()

    return open_collection_service


def build_cli_deps(
    settings: Settings,
    sources: Mapping[str, SourceDefinition] = SOURCES,
    *,
    child_initializer: Callable[[], None] | None = None,
) -> CliDeps:
    """The production wiring. `child_initializer` is passed to `ScrapyJobScraper`; tests only
    (the network guard in the crawl child)."""
    relevance = RelevancePolicy(
        settings.relevance_include_keywords, settings.relevance_exclude_keywords
    )
    clock = SystemClock()
    return CliDeps(
        settings=settings,
        sources=sources,
        relevance=relevance,
        scraper=ScrapyJobScraper(sources, settings, child_initializer=child_initializer),
        open_collection_service=_make_open_collection_service(settings, relevance, clock),
        clock=clock,
        runner=SubprocessCollectionRunner(),
        sleep=time.sleep,
        scheduler_factory=lambda: BlockingScheduler(timezone=settings.scrape_timezone),
    )
