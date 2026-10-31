"""Helpers for tests that need a database: Alembic runner and a seeded-job builder."""

import asyncio
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import text

from take_jobs.domain.models import ScrapedJob
from take_jobs.infrastructure.db.session import make_engine

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def alembic_config(url: str) -> Config:
    config = Config(str(PROJECT_ROOT / "alembic.ini"))
    config.set_main_option("sqlalchemy.url", url)
    config.attributes["configure_logger"] = False  # keep pytest's logging untouched
    return config


async def upgrade(url: str, revision: str = "head") -> None:
    # `migrations/env.py` calls asyncio.run, so it needs a thread without a running loop.
    await asyncio.to_thread(command.upgrade, alembic_config(url), revision)


async def downgrade(url: str, revision: str = "base") -> None:
    await asyncio.to_thread(command.downgrade, alembic_config(url), revision)


def scraped_job(external_id: str, **overrides: str | None) -> ScrapedJob:
    fields: dict[str, str | None] = {
        "source": "vagas",
        "title": "Desenvolvedor Python",
        "url": f"https://example.test/vagas/{external_id}",
        "company": "Acme",
        "location": "São Paulo - SP",
        "description": "Construção de APIs.",
        "published_label": "28 out",
    }
    fields.update(overrides)
    return ScrapedJob(external_id=external_id, **fields)  # type: ignore[arg-type]


def fetch(url: str, sql: str, **params: object) -> list[tuple]:
    """Run one query on a fresh engine and return the rows (sync; for tests that cannot be async,
    such as the ones that call `main()`, which runs its own event loops)."""

    async def query() -> list[tuple]:
        engine = make_engine(url)
        try:
            async with engine.connect() as connection:
                rows = (await connection.execute(text(sql), params)).all()
                return [tuple(row) for row in rows]
        finally:
            await engine.dispose()

    return asyncio.run(query())


def execute(url: str, sql: str, **params: object) -> None:
    """Run one statement in its own transaction on a fresh engine (sync, like `fetch`)."""

    async def statement() -> None:
        engine = make_engine(url)
        try:
            async with engine.begin() as connection:
                await connection.execute(text(sql), params)
        finally:
            await engine.dispose()

    asyncio.run(statement())
