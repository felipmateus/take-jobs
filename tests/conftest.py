"""Session-wide pytest configuration and the shared database fixtures.

The network guard itself comes from `addopts` in `pyproject.toml`. Here the testcontainers
host is added to `--allow-hosts` when Docker is not reachable through loopback.

Database fixtures (used by `tests/integration/` and `tests/e2e/`): one PostgreSQL 17 container per
session, migrations applied once. They are lazy, so unit tests never start Docker. Truncating the
tables before every test is opt-in: the conftest of each Docker-backed directory declares the
autouse fixture that requests `clean_tables`.
"""

import asyncio
import contextlib
import os
import sys
import time
import uuid
import warnings
from collections.abc import AsyncIterator, Awaitable, Callable, Iterator
from pathlib import Path
from urllib.parse import urlparse

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker
from testcontainers.community.postgres import PostgresContainer
from testcontainers.core.container import Reaper

from take_jobs.infrastructure.db.session import make_engine, make_sessionmaker
from tests.support import database

_TESTS = Path(__file__).parent
_DOCKER_BACKED = (_TESTS / "integration", _TESTS / "e2e")

if sys.platform == "darwin":
    # Docker Desktop for Mac: the per-user socket path cannot be bind-mounted into Ryuk, while
    # the /var/run/docker.sock symlink can.
    os.environ.setdefault("TESTCONTAINERS_DOCKER_SOCKET_OVERRIDE", "/var/run/docker.sock")

READY_TIMEOUT_SECONDS = 60


def _testcontainers_host() -> str | None:
    override = os.environ.get("TESTCONTAINERS_HOST_OVERRIDE")
    if override:
        return override
    docker_host = urlparse(os.environ.get("DOCKER_HOST", ""))
    if docker_host.scheme == "tcp" and docker_host.hostname:
        return docker_host.hostname
    return None


@pytest.hookimpl(tryfirst=True)
def pytest_configure(config: pytest.Config) -> None:
    host = _testcontainers_host()
    allowed = config.getoption("--allow-hosts")
    if host and allowed:
        config.option.allow_hosts = f"{allowed},{host}"


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    for item in items:
        if any(directory in item.path.parents for directory in _DOCKER_BACKED):
            item.add_marker(pytest.mark.integration)
        if _TESTS / "e2e" in item.path.parents:
            item.add_marker(pytest.mark.e2e)


_SETTINGS_KEYS = (
    "API_PORT",
    "POSTGRES_USER",
    "POSTGRES_PASSWORD",
    "POSTGRES_DB",
    "DATABASE_URL",
    "SCRAPE_CRON",
    "SCRAPE_TIMEZONE",
    "SCRAPE_ON_START",
    "SCRAPE_RUN_TIMEOUT_MINUTES",
    "SCRAPE_TERMS",
    "SCRAPE_MAX_PAGES",
    "SCRAPE_DOWNLOAD_DELAY",
    "SCRAPE_USER_AGENT",
    "RELEVANCE_INCLUDE_KEYWORDS",
    "RELEVANCE_EXCLUDE_KEYWORDS",
    "JOB_INACTIVE_AFTER_DAYS",
    "LOG_LEVEL",
)


@pytest.fixture(autouse=True)
def _isolated_settings_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    """No test sees the developer's configuration: `Settings` starts from its defaults."""
    for key in _SETTINGS_KEYS:
        monkeypatch.delenv(key, raising=False)


START_ATTEMPTS = 5
RYUK_RACE_PREFIX = "Port mapping"


def _is_ryuk_port_race(error: Exception) -> bool:
    return isinstance(error, ConnectionError) and str(error).startswith(RYUK_RACE_PREFIX)


def _start_postgres() -> PostgresContainer:
    """Start PostgreSQL, retrying only the cold-Docker Ryuk port-mapping race.

    The first container of a session first starts Ryuk and asks Docker for its published port
    right away. On a cold Docker Desktop the mapping is not there yet and `start()` raises
    `ConnectionError: Port mapping ... is not available`, which used to error every Docker-backed
    test at setup, in the first run only. The half-created reaper is dropped before each retry.

    Any other failure (bad image, a container that never gets ready, a name conflict) is raised on
    the first attempt, not retried for minutes. Each swallowed attempt emits a warning, and when
    every attempt hits the race the final error is chained to the first one.
    """
    first: Exception | None = None
    for attempt in range(1, START_ATTEMPTS + 1):
        container = PostgresContainer("postgres:17", driver="asyncpg")
        try:
            return container.start()
        except Exception as error:
            if not _is_ryuk_port_race(error):
                raise
            with contextlib.suppress(Exception):
                container.stop()
            Reaper.delete_instance()
            if first is None:
                first = error
            if attempt == START_ATTEMPTS:
                raise error from first
            warnings.warn(
                f"PostgreSQL container start attempt {attempt}/{START_ATTEMPTS} hit the Ryuk "
                f"port-mapping race ({error}); retrying",
                RuntimeWarning,
                stacklevel=2,
            )
            time.sleep(2)
    raise AssertionError("unreachable")


@pytest.fixture(scope="session")
def postgres_container() -> Iterator[PostgresContainer]:
    container = _start_postgres()
    try:
        yield container
    finally:
        container.stop()


@pytest.fixture(scope="session")
def server_url(postgres_container: PostgresContainer) -> str:
    """URL of the container's default database (no schema)."""
    return postgres_container.get_connection_url()


async def _wait_until_connectable(url: str) -> None:
    """The container reports ready from inside, but Docker Desktop may publish the host port a
    moment later; a first connection then fails and every dependent test would error at setup.
    Retry briefly instead."""
    deadline = asyncio.get_running_loop().time() + READY_TIMEOUT_SECONDS
    while True:
        engine = make_engine(url)
        try:
            async with engine.connect() as connection:
                await connection.execute(text("SELECT 1"))
            return
        except Exception:
            if asyncio.get_running_loop().time() >= deadline:
                raise
            await asyncio.sleep(0.5)
        finally:
            await engine.dispose()


@pytest_asyncio.fixture(scope="session")
async def database_url(server_url: str) -> str:
    """URL of a database with migrations applied once for the whole session."""
    await _wait_until_connectable(server_url)
    await database.upgrade(server_url)
    return server_url


@pytest_asyncio.fixture(scope="session")
async def engine(database_url: str) -> AsyncIterator[AsyncEngine]:
    engine = make_engine(database_url)
    yield engine
    await engine.dispose()


@pytest_asyncio.fixture(scope="session")
async def new_database_url(
    server_url: str, engine: AsyncEngine
) -> AsyncIterator[Callable[[], Awaitable[str]]]:
    """Factory of empty databases on the same server (migration tests need a blank one)."""
    created: list[str] = []

    async def create() -> str:
        name = f"empty_{uuid.uuid4().hex[:12]}"
        async with engine.connect() as connection:
            await connection.execution_options(isolation_level="AUTOCOMMIT")
            await connection.execute(text(f'CREATE DATABASE "{name}"'))
        created.append(name)
        return server_url.rsplit("/", 1)[0] + f"/{name}"

    yield create

    async with engine.connect() as connection:
        await connection.execution_options(isolation_level="AUTOCOMMIT")
        for name in created:
            await connection.execute(text(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))


@pytest_asyncio.fixture
async def clean_tables(engine: AsyncEngine) -> None:
    async with engine.begin() as connection:
        await connection.execute(
            text("TRUNCATE jobs, collection_runs, collection_run_results RESTART IDENTITY CASCADE")
        )


@pytest.fixture(scope="session")
def sessionmaker(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return make_sessionmaker(engine)


@pytest_asyncio.fixture
async def session(sessionmaker: async_sessionmaker[AsyncSession]) -> AsyncIterator[AsyncSession]:
    async with sessionmaker() as session:
        yield session
        await session.rollback()
