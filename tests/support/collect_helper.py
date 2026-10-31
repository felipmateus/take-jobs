"""The collector process of IT-013: `main(["collect"], deps=...)` against a real database.

`collect_helper` is a top-level function so a `spawn` process can import it. It makes itself the
leader of a new process group first (so the test can signal the whole group, as a terminal does,
and can check afterwards that nothing of it is left), then builds the dependencies inside the
process: the sources point at the fixture server and the crawl child gets the network guard.

Variant `ingest` wraps the repositories so that `upsert` announces itself through `events` and
then sleeps, which gives the test a window to send SIGTERM during ingestion.
"""

import asyncio
import os
from collections.abc import AsyncIterator, Callable
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from dataclasses import replace
from datetime import datetime, timedelta
from multiprocessing.connection import Connection
from typing import Any, Self

from take_jobs.application.services import CollectionService
from take_jobs.cli.main import CliDeps, build_cli_deps, main
from take_jobs.config import Settings
from take_jobs.domain.models import ScrapedJob, Seniority
from take_jobs.infrastructure.db.session import make_engine, make_sessionmaker
from take_jobs.infrastructure.db.uow import SqlAlchemyUnitOfWork
from take_jobs.infrastructure.scraping.registry import SOURCES, with_base_url
from tests.support.socket_guard import install_test_socket_guard

UPSERT_DELAY_S = 2.0


class _SlowJobs:
    def __init__(self, inner: Any, events: Connection) -> None:
        self._inner = inner
        self._events = events

    async def upsert(self, job: ScrapedJob, seniority: Seniority | None, seen_at: datetime) -> bool:
        self._events.send("upsert_started")
        await asyncio.sleep(UPSERT_DELAY_S)
        return await self._inner.upsert(job, seniority, seen_at)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._inner, name)


class _SlowUnitOfWork:
    def __init__(self, inner: SqlAlchemyUnitOfWork, events: Connection) -> None:
        self._inner = inner
        self._events = events

    async def __aenter__(self) -> Self:
        await self._inner.__aenter__()
        self.jobs = _SlowJobs(self._inner.jobs, self._events)
        self.runs = self._inner.runs
        self.probe = self._inner.probe
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self._inner.__aexit__(*exc)


def _slow_ingestion(
    deps: CliDeps, events: Connection
) -> Callable[[], AbstractAsyncContextManager[CollectionService]]:
    settings = deps.settings

    @asynccontextmanager
    async def open_collection_service() -> AsyncIterator[CollectionService]:
        engine = make_engine(settings.database_url)
        try:
            sessionmaker = make_sessionmaker(engine)
            yield CollectionService(
                lambda: _SlowUnitOfWork(SqlAlchemyUnitOfWork(sessionmaker), events),
                deps.relevance,
                deps.clock,
                timedelta(minutes=settings.scrape_run_timeout_minutes),
            )
        finally:
            await engine.dispose()

    return open_collection_service


def collect_helper(database_url: str, server_url: str, variant: str, events: Connection) -> None:
    """Run `take-jobs collect` and exit with its code. `variant` is `crawl` or `ingest`."""
    os.setpgid(0, 0)
    settings = Settings(_env_file=None, database_url=database_url, scrape_terms="python")
    deps = build_cli_deps(
        settings,
        with_base_url(SOURCES, server_url),
        child_initializer=install_test_socket_guard,
    )
    if variant == "ingest":
        deps = replace(deps, open_collection_service=_slow_ingestion(deps, events))
    events.send("ready")
    raise SystemExit(main(["collect"], deps=deps))
