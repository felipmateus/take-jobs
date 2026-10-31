"""IT-014: the O5 success-rate query of `_spec.md` > Monitoring, as the README documents it."""

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from tests.static.support import ROOT

METRICS_SQL = ROOT / "src" / "take_jobs" / "infrastructure" / "db" / "metrics.sql"
TZ = "America/Sao_Paulo"
EXPECTED = 24  # 2 sources x 12 terms

# Local noon of the day `:n` days before today (in :tz), so the run date is unambiguous.
NOON = "((now() AT TIME ZONE :tz)::date - CAST(:n AS integer) + time '12:00') AT TIME ZONE :tz"

INSERT_RUN = """
INSERT INTO collection_runs (trigger, status, started_at, finished_at, expected_combinations)
VALUES ('scheduled', :status, {noon}, {finished}, :expected)
RETURNING id
"""

INSERT_SUCCESSES = """
INSERT INTO collection_run_results
    (run_id, source, term, status, pages, new_count, seen_again_count, discarded_count)
SELECT :run_id, s.source, 'term ' || t, 'success', 1, 0, 0, 0
FROM unnest(ARRAY['vagas', 'infojobs']) AS s(source), generate_series(1, 12) AS t
"""


# PostgreSQL's `now()` is the start time of the *transaction*. Seeding and querying on one
# connection, in one transaction that is never committed, gives every statement the same "today",
# so the test cannot flake when midnight in `TZ` passes while it runs (review round 7, issue 004).


async def _seed_run(
    connection: AsyncConnection, days_ago: int, *, status: str, successes: int = 0
) -> None:
    run_id = (
        await connection.execute(
            text(INSERT_RUN.format(noon=NOON, finished="NULL" if status == "running" else NOON)),
            {"status": status, "tz": TZ, "n": days_ago, "expected": EXPECTED},
        )
    ).scalar_one()
    if successes:
        assert successes == EXPECTED
        await connection.execute(text(INSERT_SUCCESSES), {"run_id": run_id})


async def _success_rate(connection: AsyncConnection) -> float:
    value = (
        await connection.execute(
            text(METRICS_SQL.read_text(encoding="utf-8")), {"tz": TZ, "expected": EXPECTED}
        )
    ).scalar_one()
    return float(value)


async def test_it014a_counts_crashed_and_missing_days_as_failures(engine: AsyncEngine) -> None:
    async with engine.connect() as connection:  # rolled back on exit: nothing is committed
        for days_ago in range(1, 6):
            await _seed_run(connection, days_ago, status="success", successes=EXPECTED)
        await _seed_run(connection, 6, status="failed")  # crash: no results, expected still 24
        # D-7 has no run: counts :expected, all failed.

        assert await _success_rate(connection) == pytest.approx(71.4)  # 120 / 168


@pytest.mark.parametrize("today", ["none", "running"])
async def test_it014b_today_is_outside_the_window(engine: AsyncEngine, today: str) -> None:
    async with engine.connect() as connection:
        for days_ago in range(1, 8):
            await _seed_run(connection, days_ago, status="success", successes=EXPECTED)
        if today == "running":
            await _seed_run(connection, 0, status="running")

        assert await _success_rate(connection) == pytest.approx(100.0)
