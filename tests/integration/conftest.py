"""Integration tests (real PostgreSQL): every test starts from empty tables.

The database fixtures are shared and live in `tests/conftest.py`.
"""

import pytest_asyncio


@pytest_asyncio.fixture(autouse=True)
async def _empty_tables(clean_tables: None) -> None:
    return None
