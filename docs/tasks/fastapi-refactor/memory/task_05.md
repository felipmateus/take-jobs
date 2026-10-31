# task_05 memory

## Outcome
Completed. `take_jobs.application.{errors,queries,services}`; `tests/fakes.py`; `tests/unit/application/test_{job_query_service,collection_run_query_service,collection_service}.py` (43 tests); `tests/integration/test_collection_service.py` (IT-008 + a commit test). Full suite 265 passed; coverage domain+application 99.55% (gate 80%).

## Decisions
- `JobQuery` and `JobView` live in `application/queries.py` (also importable from `application.services`). `JobQuery(q, sources: frozenset, location, seniorities: frozenset, seen_from: date, seen_to: date, include_inactive, page=1, size=20)`. `JobView(Job)` is a frozen subclass with `active`, built by `JobView.of(job, active=...)`.
- `application.errors` defines `JobNotFoundError(job_id)`, `CollectionRunNotFoundError(run_id)`, `InvalidPeriodError(seen_from, seen_to)` and re-exports the four domain errors.
- Period bounds: start of `seen_from` in tz as UTC; end of `seen_to` = start of the next local day minus 1 microsecond (DST-safe). Page/size are passed through, not validated (API task validates).
- `start_run`: `get_active`; live (age <= run_timeout, boundary inclusive) -> `RunAlreadyActiveError`; stale -> `mark_interrupted` (a `RunTakenOverError` there is suppressed) then `start`, all in one UoW.
- `complete_run` reads the run first (`runs.get`); a missing or non-running run raises `RunTakenOverError` before any upsert. Then ingests (relevance -> `classify_seniority` -> `upsert`; `new` iff upsert returns True, else `seen_again`; irrelevant -> `discarded`), `runs.finish`, then `before_commit()` last. The returned `CollectionRun` is built with `dataclasses.replace` from the pre-read run (no re-read, so the UoW event log is exactly upserts, finish, before_commit, commit). A combination is `failed` iff `outcome.error is not None`. One `clock.now()` serves as `seen_at` and `finished_at`.
- `fail_run`: fresh UoW, `finish(FAILED, (), now, error)` then `get`; the caller supplies the full text (`ingest failed: <Type>: <msg>` is the CLI's job).
- Fakes (`tests/fakes.py`): `InMemoryStore` (data, event log, injectable `finish_error`/`upsert_error`/`ping_error`, `empty` override, `add_job`/`add_run` seeders), `InMemoryUnitOfWork(store)` (snapshot on enter, restore on exception, events `commit`/`rollback`), `InMemoryJobRepository` (`searches` records criteria; `search` does no filtering), `InMemoryCollectionRunRepository`, `InMemoryJobStoreProbe` (`ping_calls`), `FixedClock(now).advance()`, `NOW = 2026-10-30T12:00Z`. Events: `start`, `mark_interrupted`, `upsert:<source>/<id>`, `finish`, `commit`, `rollback`; tests append their own markers to `store.events`.

## Handoff
- task_06 (CLI): build `CollectionService(lambda: SqlAlchemyUnitOfWork(sessionmaker), RelevancePolicy(...), clock, timedelta(minutes=run_timeout))`; pass `before_commit=phase.clear_cancellable`; compose `ingest failed: ...` text before `fail_run`. For fake-based CLI tests use `CollectionService(lambda: InMemoryUnitOfWork(store), ...)`.
- task_07 (API): `JobQueryService(SqlAlchemyJobRepository(session), clock, timedelta(days=...), ZoneInfo(...))`; map `InvalidPeriodError`, `JobNotFoundError`, `CollectionRunNotFoundError`.

## Evidence
`uv run ruff format --check`, `ruff check`, `lint-imports` (8 kept) clean; `uv run pytest -q --cov=take_jobs.domain --cov=take_jobs.application --cov-fail-under=80` 265 passed, 99.55%; `tests/integration/test_collection_service.py` 2 passed (real postgres:17 via testcontainers).
