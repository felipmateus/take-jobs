---
status: completed
title: "Task 7: HTTP API: search, detail, run history, health and docs"
type: feature
complexity: medium
---

# Task 7: HTTP API: search, detail, run history, health and docs

## Overview

This task delivers the read-only JSON API: job search, job detail, the run list and detail, health, and the OpenAPI/Swagger docs. All errors share one shape. Dependencies are injected through FastAPI `Depends`, and the app comes from `create_app(settings, sources)`. With this task, Slice 1 is complete: collect, then search, end to end.

## Shippable Outcome

- **Outcome:** `uvicorn --factory take_jobs.api.app:create_app` serves every route in `_dx.md` › HTTP API, with the documented validation, error codes, pagination and ordering. After a fixture-backed `take-jobs collect`, `GET /jobs?q=python` returns the collected jobs (E2E-001).
- **Verify in this task:** UT-090–UT-103 (dependency overrides), IT-011 (search p95 < 300 ms at 50k jobs, including 1–2 character queries) and E2E-001–E2E-005 (synchronous, `TestClient` plus `main`).
- **Integration verification:** MAN-001 in task_09 runs the same API in Docker Compose.

## Requirements

- **Routes, schemas, error shape and codes:** exactly as in `_dx.md` and `_spec.md` › API Endpoints.
- **`source` enum:** comes from the injected registry keys (US-007); the API package never names a site.
- **DI chain:**
  - `get_settings` reads `request.app.state.settings`, never a process-global cache;
  - the engine and sessionmaker are created in the lifespan and disposed on shutdown;
  - every request gets its own session.
- **Error handlers:** `RequestValidationError` → `validation_error`; application errors → their codes; DB errors → `503 database_unavailable`; unknown route → `not_found`; anything else → `500 internal_error`, with no details in the body.
- **Health:** a 3-second probe timeout.
- **IT-011:** if the short-query set misses the target, record the numbers and return to the user. Do not change the contract.
- **Docker:** IT-011 and E2E need it. If Docker is unavailable, stop and report.

## Subtasks

- [x] 7.1 Write `api/app.py` (`create_app`, lifespan) and `api/dependencies.py`.
- [x] 7.2 Write `api/schemas.py` and routers `jobs`, `runs`, `health`.
- [x] 7.3 Write the error handlers and the OpenAPI error responses.
- [x] 7.4 Write the unit tests with overrides; IT-011; E2E-001–E2E-005, with the journey fixtures from task_04.

## Implementation Details

### Relevant Files

- `src/take_jobs/api/{app,dependencies,schemas,errors}.py`, `src/take_jobs/api/routers/{jobs,runs,health}.py` — new.
- `tests/unit/api/test_*.py`, `tests/integration/test_search_perf.py`, `tests/e2e/test_*.py` — new.

### Dependent Files

- `src/take_jobs/application/*` (task_05), `src/take_jobs/cli/main.py` (task_06), `tests/support/*` (task_04).

### Related ADRs

- [ADR-001](adrs/adr-001.md) — the API is a composition root; infrastructure is imported only in `app`/`dependencies`.
- [ADR-005](adrs/adr-005.md) — search performance.

## Deliverables

- The API package.
- Passing unit, performance and E2E tests.

## Tests

- [x] UT-090–UT-103 — parameters, validation, error mapping, health, OpenAPI, repeated parameters.
- [x] IT-011 — performance at 50k jobs.
- [x] E2E-001 — collect, then search, detail and run history.
- [x] E2E-002 — relevance and deduplication journey.
- [x] E2E-003 — lifecycle and reactivation.
- [x] E2E-004 — partial failure.
- [x] E2E-005 — health with and without a database.

## Success Criteria

- Slice 1 is demonstrable: E2E-001 passes.
