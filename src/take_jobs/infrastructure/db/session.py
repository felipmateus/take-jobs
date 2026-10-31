"""Engine and session factory (rule 24: a 5-second connect timeout)."""

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

CONNECT_TIMEOUT_SECONDS = 5

# asyncpg prepares every statement. After five executions PostgreSQL may switch a prepared
# statement to a generic plan, which cannot see the search text and so gives up the recency index
# for 1-2 character `q` values: p95 went from about 80 ms to about 290 ms at 50,000 jobs (IT-011).
# Custom plans cost a fraction of a millisecond of planning per query.
SERVER_SETTINGS = {"plan_cache_mode": "force_custom_plan"}


def make_engine(url: str) -> AsyncEngine:
    """Build an async engine whose connection attempts give up after 5 s, so a collector
    recording `fail_run` cannot hang on an unreachable database."""
    return create_async_engine(
        url,
        connect_args={"timeout": CONNECT_TIMEOUT_SECONDS, "server_settings": SERVER_SETTINGS},
    )


def make_sessionmaker(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False)
