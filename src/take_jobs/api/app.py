"""The FastAPI composition root: `uvicorn --factory take_jobs.api.app:create_app`."""

from collections.abc import AsyncIterator, Mapping
from contextlib import asynccontextmanager

from fastapi import FastAPI

from take_jobs.api.errors import register_error_handlers
from take_jobs.api.routers import health, jobs, runs
from take_jobs.config import Settings
from take_jobs.infrastructure.db.session import make_engine, make_sessionmaker
from take_jobs.infrastructure.scraping.registry import SOURCES, SourceDefinition
from take_jobs.log import configure_logging


@asynccontextmanager
async def _lifespan(app: FastAPI) -> AsyncIterator[None]:
    """The engine lives as long as the application and is disposed on shutdown. It does not
    connect here, so the API starts (and answers `/health` with 503) while the database is down."""
    engine = make_engine(app.state.settings.database_url)
    app.state.engine = engine
    app.state.sessionmaker = make_sessionmaker(engine)
    try:
        yield
    finally:
        await engine.dispose()


def create_app(
    settings: Settings | None = None, sources: Mapping[str, SourceDefinition] | None = None
) -> FastAPI:
    app = FastAPI(
        title="take-jobs",
        version="2.0.0",
        description="Job listings collected from the registered sources.",
        lifespan=_lifespan,
    )
    app.state.settings = settings if settings is not None else Settings()
    configure_logging(app.state.settings.log_level)
    app.state.sources = sources if sources is not None else SOURCES
    register_error_handlers(app)
    app.include_router(jobs.build_router(sorted(app.state.sources)))
    app.include_router(runs.router)
    app.include_router(health.router)
    return app
