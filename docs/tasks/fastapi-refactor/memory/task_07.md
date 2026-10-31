# task_07 memory

## Outcome
Completed. The read-only HTTP API: `src/take_jobs/api/{app,dependencies,errors,params,schemas}.py` and `routers/{jobs,runs,health}.py`. Tests: `tests/unit/api/{conftest,test_api}.py` (38: UT-090-UT-103 plus DI/lifespan/shape cases), `tests/integration/test_search_perf.py` (IT-011), `tests/e2e/{conftest,test_journeys,test_health}.py` (E2E-001-E2E-005 plus a "every route is 503 with the database down" test), helper `tests/support/journey.py`. Full suite 355 passed, twice back to back (about 111 s each). `uvicorn --factory take_jobs.api.app:create_app` smoke-tested by hand (health 503 with a dead database, `/docs` 200, 422 and `not_found` bodies).

## Decisions
- `routers.jobs.build_router(source_ids)` is a factory: the `source` parameter is `Literal[ids]`, so OpenAPI shows the enum from the injected registry (`create_app` passes `sorted(sources)`). `routers.runs.router` and `routers.health.router` are plain module routers.
- Error shape lives in `api/errors.py`. Validation `details`: one entry per field (first error wins), field = `loc` without the leading `query`/`path` and without list indexes (`source`, `job_id`). 405 -> `method_not_allowed`, other HTTP errors -> `http_error` (the spec is silent). `Exception` handler logs `event=api_unhandled_error` with the traceback and answers the fixed 500 body; tests that expect it use `TestClient(..., raise_server_exceptions=False)`.
- `database_unavailable` also covers `OSError` (not only the spec's `OperationalError`/`InterfaceError`/pool `TimeoutError`): asyncpg raises a raw `ConnectionRefusedError` while opening a connection, which would otherwise be a 500. Verified by mutation (E2E test fails without it).
- `page` has a ceiling of `MAX_PAGE = 1_000_000_000` (`api/params.py`). Without it `page=99999999999999999999` made `OFFSET` overflow bigint and answered `500 internal_error`. The documented rule (`page >= 1`) is unchanged for every realistic value; the OpenAPI document now shows `maximum`.
- Health: `asyncio.timeout(3.0)` around `probe.ping()`; any exception -> `503 {"status":"unavailable","database":"unreachable"}`, logged as `api_health_failed`.
- Response models forbid extra keys (`extra="forbid"`, `from_attributes=True`), so `RunDetailOut` can validate documents produced elsewhere. UT-074 (task_06) now also validates the CLI `--json` against the real `RunDetailOut`; E2E-001 compares the CLI document with the API's.
- The lifespan creates the engine and sessionmaker from `app.state.settings` and disposes the engine on shutdown. It does not connect, so the API starts with the database down. A `TestClient` without `with` does not run the lifespan (fine for override-based unit tests; E2E uses `with`).
- `get_clock` returns `SystemClock()`; it is a dependency so tests can override it.

## Root cause found for IT-011 (no contract change)
First IT-011 run: 3+ character set p95 about 45 ms, but the 1-2 character set p95 360 ms (`c` and the others about 285 ms after the first three). Cause: asyncpg prepares every statement, and after the 5th execution PostgreSQL switches to a generic plan; with `q` unknown at plan time it drops the `ix_jobs_recency` index scan with early exit. Fix in the persistence layer, not the API: `make_engine` passes `server_settings={"plan_cache_mode": "force_custom_plan"}` (`infrastructure/db/session.py`). Regression coverage: IT-011 itself and `test_make_engine_forces_custom_plans` (the task_03 connect-args test now checks only `timeout`). Numbers, Docker Desktop on macOS, postgres:17, 50,000 jobs:
- Before the fix: 3+ chars p50 17.7 ms / p95 45.2 ms; 1-2 chars p50 283 ms / p95 294-315 ms (over the limit in one of three runs, 375 ms max).
- After the fix: 3+ chars p50 18-22 ms / p95 47-50 ms; 1-2 chars p50 47-48 ms / p95 70-83 ms (six runs, all passing).
`EXPLAIN` of a selective 3+ char `q` (`kubernetes`) uses `ix_jobs_search_text_trgm` (Bitmap Index Scan). The target (p95 < 300 ms) is met for both sets, so nothing needs to go back to the user, but the 1-2 character queries are a sequential scan (about 35 ms server time for a miss like `go`) and will grow linearly with the table (ADR-005 Risks).

## Test isolation: the "whole suite errors at setup" flake (reproduced)
Reproduced on the first Docker-backed run after a pause: `ConnectionError: Port mapping for container ... and port 8080 is not available`, raised inside `PostgresContainer.start()` while testcontainers creates its Ryuk reaper (it asks Docker for the published port immediately; on a cold Docker Desktop the mapping is not there yet). The session-scoped `postgres_container` fixture failed, so every dependent test errored at setup. Fix in `tests/conftest.py`: `_start_postgres()` retries (5 attempts, 2 s apart) and calls `Reaper.delete_instance()` before each retry (otherwise the half-created `testcontainers-ryuk-<session>` container makes the next attempt fail on the name). Also `_wait_until_connectable` retries a `SELECT 1` (up to 60 s) before migrations, in case the host port is published late. The retry path itself was not forced again after the fix (the race needs a cold Docker); the leftover Ryuk container of the failed attempt disappeared by itself.

## Shared fixtures moved
The database fixtures (container, `server_url`, `database_url`, `engine`, `new_database_url`, `sessionmaker`, `session`, `clean_tables`) now live in `tests/conftest.py`; they are lazy, so unit tests never start Docker. `clean_tables` is no longer autouse: `tests/integration/conftest.py` and `tests/e2e/conftest.py` each declare an autouse `_empty_tables` that requests it. `pytest_collection_modifyitems` marks anything under `integration/` or `e2e/` as `integration`, and `e2e/` also as `e2e` (new marker in `pyproject.toml`; `-m integration` still selects the Docker-backed tests).

## Other changes
- `pyproject.toml`: removed `unmatched_ignore_imports_alerting = "none"` from the api-infrastructure contract (the modules exist now; 7 ignored imports, 8 contracts kept); added the `e2e` marker.
- `import-linter`: only `api.app` and `api.dependencies` import infrastructure.

## Handoff
- task_08 (scheduler) and task_09 (Docker Compose): the API runs with `uvicorn --factory take_jobs.api.app:create_app --host 0.0.0.0 --port 8000`; it reads `DATABASE_URL`, `SCRAPE_TIMEZONE` and `JOB_INACTIVE_AFTER_DAYS` from `Settings()`; `/health` is the natural container healthcheck (503 while the database is down). MAN-001 owns the Compose run.
- E2E helper for later journeys: `tests.support.journey.Journey(database_url, fixture_server, terms)` with `.collect(capsys, *args)` and `.api()` (context manager).
- Follow-up (not done): `starlette.testclient` prints a deprecation warning, "Using `httpx` with `starlette.testclient` is deprecated; install `httpx2` instead". Harmless today; a later dependency bump may need to switch.
- Follow-up (not done): 1-2 character `q` is a sequential scan; if the table grows well beyond 50k rows, revisit ADR-005 (for example require 3+ characters, or add a pre-filter).

## Evidence
- `uv run ruff format --check` (176 files), `ruff check`, `lint-imports` (8 kept) clean.
- `uv run pytest -q --cov=take_jobs`: 355 passed (1:51), total coverage 94%; run twice back to back, both 355 passed; second run with `--cov=take_jobs.domain --cov=take_jobs.application --cov-fail-under=80` 99%.
- `uv run pytest tests/unit/api -q` 38 passed; `tests/e2e` 7 passed (about 28 s); `tests/integration/test_search_perf.py` 1 passed (about 12 s).
- Mutations: dropping `OSError` from `DATABASE_ERRORS` fails the E2E 503 test; removing `force_custom_plan` fails IT-011 (294-375 ms).
- No spawned process and no container left (`docker ps -a` shows only the user's exited `mrt-local-pg`).
