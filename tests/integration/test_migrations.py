"""IT-001: the Alembic revision creates, removes and re-creates the schema."""

from collections.abc import Awaitable, Callable

import pytest
from alembic.script import ScriptDirectory
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import create_async_engine

from tests.support import database

TABLES = {"jobs", "collection_runs", "collection_run_results"}
INDEXES = {
    "uq_jobs_source_external_id",
    "ix_jobs_recency",
    "ix_jobs_search_text_trgm",
    "ix_jobs_location_trgm",
    "ix_jobs_source",
    "ix_jobs_seniority",
    "uq_collection_runs_single_running",
    "ix_collection_runs_started_at",
    "uq_run_results_combination",
}

NewDatabase = Callable[[], Awaitable[str]]


async def _scalars(url: str, statement: str) -> set[str]:
    engine = create_async_engine(url)
    try:
        async with engine.connect() as connection:
            return set((await connection.execute(text(statement))).scalars())
    finally:
        await engine.dispose()


async def _schema(url: str) -> dict[str, set[str]]:
    return {
        "tables": await _scalars(
            url,
            "SELECT tablename FROM pg_tables WHERE schemaname = 'public' "
            "AND tablename <> 'alembic_version'",
        ),
        "extensions": await _scalars(url, "SELECT extname FROM pg_extension"),
        "indexes": await _scalars(
            url, "SELECT indexname FROM pg_indexes WHERE schemaname='public'"
        ),
        "functions": await _scalars(
            url, "SELECT proname FROM pg_proc WHERE proname = 'immutable_unaccent'"
        ),
    }


async def test_upgrade_downgrade_upgrade(new_database_url: NewDatabase) -> None:
    url = await new_database_url()

    await database.upgrade(url)
    schema = await _schema(url)
    assert schema["tables"] == TABLES
    assert {"unaccent", "pg_trgm"} <= schema["extensions"]
    assert schema["functions"] == {"immutable_unaccent"}
    assert schema["indexes"] >= INDEXES

    await database.downgrade(url)
    schema = await _schema(url)
    assert schema["tables"] == set()
    assert schema["functions"] == set()
    assert not {"unaccent", "pg_trgm"} & schema["extensions"]

    await database.upgrade(url)
    schema = await _schema(url)
    assert schema["tables"] == TABLES
    assert schema["indexes"] >= INDEXES


async def test_there_is_a_single_head_named_0001() -> None:
    script = ScriptDirectory.from_config(database.alembic_config("postgresql+asyncpg://x/y"))
    assert script.get_heads() == ["0001"]


async def test_ddl_matches_the_spec(database_url: str) -> None:
    columns = await _scalars(
        database_url,
        "SELECT table_name || '.' || column_name || ':' || data_type "
        "|| ':' || is_nullable || ':' || coalesce(is_generated, '') "
        "FROM information_schema.columns WHERE table_schema = 'public'",
    )
    assert "jobs.published_label:text:YES:NEVER" in columns
    assert "jobs.search_text:text:YES:ALWAYS" in columns
    assert "jobs.first_seen_at:timestamp with time zone:NO:NEVER" in columns
    assert "collection_runs.expected_combinations:integer:NO:NEVER" in columns
    assert "collection_runs.finished_at:timestamp with time zone:YES:NEVER" in columns
    assert "collection_run_results.term:text:NO:NEVER" in columns

    definitions = await _scalars(
        database_url,
        "SELECT indexdef FROM pg_indexes WHERE indexname = 'uq_collection_runs_single_running'",
    )
    (definition,) = definitions
    assert "UNIQUE" in definition
    assert "WHERE" in definition
    assert "'running'" in definition


@pytest.mark.parametrize(
    "statement",
    [
        pytest.param(
            "INSERT INTO jobs (source, external_id, title, url, seniority, first_seen_at,"
            " last_seen_at) VALUES ('s', '1', 't', 'u', 'boss', now(), now())",
            id="seniority",
        ),
        pytest.param(
            "INSERT INTO collection_runs (trigger, status, started_at, expected_combinations)"
            " VALUES ('manual', 'running', now(), 0)",
            id="expected_combinations_positive",
        ),
        pytest.param(
            "INSERT INTO collection_runs (trigger, status, started_at, expected_combinations)"
            " VALUES ('cron', 'running', now(), 1)",
            id="trigger",
        ),
        pytest.param(
            "INSERT INTO collection_runs (trigger, status, started_at, expected_combinations)"
            " VALUES ('manual', 'paused', now(), 1)",
            id="status",
        ),
    ],
)
async def test_check_constraints_reject_invalid_rows(engine, statement: str) -> None:
    with pytest.raises(IntegrityError):
        async with engine.begin() as connection:
            await connection.execute(text(statement))
