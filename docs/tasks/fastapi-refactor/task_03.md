---
status: completed
title: "Task 3: Persistence: PostgreSQL schema, repositories and unit of work"
type: backend
complexity: high
---

# Task 3: Persistence: PostgreSQL schema, repositories and unit of work

## Overview

This task implements the PostgreSQL storage behind the domain ports:
- Alembic migration `0001`, with the extensions, `immutable_unaccent`, three tables and every index;
- the async SQLAlchemy models;
- the job and run repositories, the job store probe and the unit of work;
- an engine factory with a 5-second connect timeout.

## Shippable Outcome

- **Outcome:** `alembic upgrade head` creates the schema from `_spec.md` › Data Models. The repositories satisfy the domain ports against a real PostgreSQL 17:
  - upsert by `(source, external_id)` reports new vs seen-again;
  - search is accent- and case-insensitive and literal-safe;
  - the period, active, source, location and seniority filters work;
  - ordering and pagination match the spec;
  - only one run can be running at a time;
  - finishing a run is conditional and happens once;
  - list views carry totals;
  - `latest_finished` and the probe work.
- **Verify in this task:** IT-001–IT-006 and IT-010, on testcontainers PostgreSQL 17.
- **Integration verification:** IT-011 (performance, task_07) and IT-014 (O5 query, task_10) reuse this schema.

## Requirements

- **DDL:** exactly as in `_spec.md` › Data Models.
  - `published_label` is `text`, and `collection_runs.expected_combinations` exists.
  - `search_text` is a generated column with `coalesce`, as in ADR-005.
  - `uq_collection_runs_single_running` is a partial unique index.
- **Upsert:** `ON CONFLICT … DO UPDATE … RETURNING (xmax = 0)`. `first_seen_at` is never in the `SET` list (Safety Invariant 4).
- **Finish:** `finish`, `mark_interrupted` and the failure path are conditional on `status = 'running'`. When 0 rows are affected they raise `RunTakenOverError` (Safety Invariant 2).
- **Search escaping:** `q` and `location` escape `%`, `_` and `\` (Business Rule 19, ADR-005).
- **Engine:** `infrastructure.db.session.make_engine(url)` sets `connect_args={"timeout": 5}` (rule 24).
- **Unit of work:** `SqlAlchemyUnitOfWork` exposes `jobs`, `runs` and `probe` on one session. It commits on success in `__aexit__` and rolls back on error.
- **Boundaries:** this package imports only `take_jobs.domain` and SQLAlchemy (ADR-001).
- **Docker:** the integration tests need it. If Docker is unavailable, stop and report; do not mark this task `completed`.

## Subtasks

- [x] 3.1 Set up `alembic.ini` and `migrations/` env (async), plus revision `0001`.
- [x] 3.2 Write the SQLAlchemy models and `make_engine`/sessionmaker.
- [x] 3.3 Implement `SqlAlchemyJobRepository` (upsert, get, search).
- [x] 3.4 Implement `SqlAlchemyCollectionRunRepository` (start, get_active, latest_finished, mark_interrupted, finish, get, list with totals).
- [x] 3.5 Implement `SqlAlchemyJobStoreProbe` and `SqlAlchemyUnitOfWork`.
- [x] 3.6 Write the testcontainers fixtures (session container, migrations once, per-test cleanup) and the integration tests.

## Implementation Details

### Relevant Files

- `alembic.ini`, `migrations/env.py`, `migrations/versions/0001_create_jobs_and_runs.py` — new.
- `src/take_jobs/infrastructure/db/{models,session,job_repository,run_repository,probe,uow}.py` — new.
- `tests/integration/conftest.py`, `tests/integration/test_repositories.py`, `tests/integration/test_migrations.py` — new.

### Dependent Files

- `src/take_jobs/domain/ports.py` (task_02) — the contracts implemented here.

### Related ADRs

- [ADR-005: Accent-insensitive search with unaccent + pg_trgm generated column](adrs/adr-005.md) — the search column, the indexes and escaping.

## Deliverables

- The migration, models, repositories, unit of work and probe.
- Passing integration tests.

## Tests

- [x] IT-001 — migrations up, down and up again.
- [x] IT-002 — upsert semantics.
- [x] IT-003 — text search, including literal wildcards and the null company/description case.
- [x] IT-004 — filters.
- [x] IT-005 — ordering and pagination.
- [x] IT-006 — run repository: single running run, single finish, totals in list views, `latest_finished`.
- [x] IT-010 — probe `is_empty` and `ping`, and the 3-second failure bound.

## Success Criteria

- `uv run pytest -m integration tests/integration/test_repositories.py tests/integration/test_migrations.py` passes with Docker running.
