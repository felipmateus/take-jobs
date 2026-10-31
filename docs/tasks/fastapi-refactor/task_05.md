---
status: completed
title: "Task 5: Application services: search, run history and collection"
type: backend
complexity: high
---

# Task 5: Application services: search, run history and collection

## Overview

This task implements the use cases that the CLI and the API call: `JobQueryService` for search and detail, `CollectionRunQueryService` for run history, and `CollectionService`. The collection service covers start, complete, fail, startup reason, ping and get_run. It applies relevance, seniority, deduplication counts and final status in one transaction.

## Shippable Outcome

- **Outcome:** each service behaves as specified when given ports:
  - search builds criteria with the activity cutoff, the time-zone date bounds and blank handling, and raises `InvalidPeriodError`/`JobNotFoundError`;
  - `start_run` handles a stale run as interrupted, or refuses with `RunAlreadyActiveError`;
  - `complete_run` filters, classifies, upserts, counts new/seen_again/discarded per combination and finishes atomically, calling `before_commit` as the last statement inside the unit of work;
  - `fail_run` records the error in a fresh transaction;
  - `startup_reason` and `ping` delegate correctly.
- **Verify in this task:** UT-050–UT-068 (with fakes) and IT-008 (real database: atomic rollback, then `fail_run`).
- **Integration verification:** the CLI (task_06) and the API (task_07) use these services.

## Requirements

- **Signatures:** exactly as in `_spec.md` › Core Interfaces (`take_jobs/application/services.py`), including `complete_run(..., *, before_commit=None)` and `get_run`.
- **Boundaries:** depends only on `take_jobs.domain` (ADR-001); the application layer has no framework imports.
- **Business rules:** 1–3, 5, 9, 12–14 and 21–22.
- **Fakes:** the in-memory fakes in `tests/fakes.py` (repositories, UnitOfWork with probe and an event log, FixedClock) are created here and reused by later tasks.
- **Docker:** IT-008 needs it. If Docker is unavailable, stop and report.

## Subtasks

- [x] 5.1 Write `application/errors.py` and the `JobQuery`/`JobView` types.
- [x] 5.2 Implement `JobQueryService` and `CollectionRunQueryService`.
- [x] 5.3 Implement `CollectionService`, including the `before_commit` ordering.
- [x] 5.4 Write `tests/fakes.py` and the unit tests; write IT-008.

## Implementation Details

### Relevant Files

- `src/take_jobs/application/{services,errors}.py` — new.
- `tests/fakes.py` — new and shared.
- `tests/unit/application/test_*.py`, `tests/integration/test_collection_service.py` — new.

### Dependent Files

- `src/take_jobs/domain/*` (task_02).
- `src/take_jobs/infrastructure/db/*` (task_03), for IT-008.

### Related ADRs

- [ADR-002](adrs/adr-002.md) — ingest as one transaction; `fail_run` in a fresh transaction.

## Deliverables

- The services, the shared fakes and passing tests.

## Tests

- [x] UT-050–UT-055 — `JobQueryService`.
- [x] UT-056–UT-064, UT-066, UT-068 — `CollectionService` start/complete/fail paths and `before_commit` ordering.
- [x] UT-065 — `CollectionRunQueryService`.
- [x] UT-067 — `startup_reason` and `ping`.
- [x] IT-008 — atomic completion, then the `ingest failed` record.

## Success Criteria

- The coverage gate (`--cov=take_jobs.domain --cov=take_jobs.application --cov-fail-under=80`) passes.
