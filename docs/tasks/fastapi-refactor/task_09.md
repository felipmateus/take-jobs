---
status: completed
title: "Task 9: Packaging: Dockerfile, Docker Compose and `.env.example`"
type: infra
complexity: medium
---

# Task 9: Packaging: Dockerfile, Docker Compose and `.env.example`

## Overview

This task packages the system so an evaluator can run it with a single `docker compose up --build`. The services are the database, migrations, the API and the scheduler, started in a guaranteed order and with every setting overridable through `.env`. No secret is committed.

## Shippable Outcome

- **Outcome:** from a clean clone with no `.env`, `docker compose up --build` gives the following sequence:
  1. `db` becomes healthy, with no "variable is not set" warnings;
  2. `migrate` runs and exits `0`;
  3. `api` answers `GET /health` on `http://localhost:8000`;
  4. `scheduler` runs the startup collection;
  5. `GET /jobs` returns real jobs within 15 minutes (O4).
- **Verify in this task:**
  - UT-110 (Compose contract);
  - IT-012 (config contract and secret scan);
  - MAN-001 (live smoke: one-command start, restart behavior, `API_PORT`);
  - MAN-003 (relevance sample of 50 jobs, at least 90% development roles).
- **Integration verification:** none beyond these. MAN-001 and MAN-003 need real network access and Docker. Record their evidence in task memory.

## Requirements

- **Compose contract:** exactly the table in `_spec.md` › System Architecture:
  - the `db` healthcheck is `["CMD-SHELL", "pg_isready -U $$POSTGRES_USER -d $$POSTGRES_DB"]`, and `db` has no `ports:`;
  - `depends_on` conditions per the table;
  - `restart: unless-stopped` for `api` and `scheduler`;
  - `scheduler` has `init: true` and `stop_grace_period: 30s`;
  - no `env_file`;
  - every key appears as `${KEY-default}` (Config Lifecycle).
- **Dockerfile:** one app image, Python 3.13 slim, `uv sync --frozen --no-dev`, non-root user. The default command is the API. Add `.dockerignore`.
- **`.env.example`:** lists every key from `_dx.md` › Config with one-line comments.
- **Secret scan scope:** per IT-012. Never quote the v1 password anywhere.

## Subtasks

- [x] 9.1 Write `Dockerfile` and `.dockerignore`.
- [x] 9.2 Write `docker-compose.yml` per the contract.
- [x] 9.3 Write `.env.example`.
- [x] 9.4 Write UT-110 and IT-012 (including secret-scan fixtures `tests/fixtures/secrets/{leak,ok}.env`).
- [x] 9.5 Run MAN-001 and MAN-003 and record the evidence (timings, outputs, sample count).

## Implementation Details

### Relevant Files

- `Dockerfile`, `.dockerignore`, `docker-compose.yml`, `.env.example` — new.
- `tests/static/test_compose.py`, `tests/static/test_secret_scan.py`, `tests/fixtures/secrets/*` — new.

### Dependent Files

- `src/take_jobs/config.py` (task_01), API (task_07), scheduler (task_08).

### Related ADRs

- [ADR-004](adrs/adr-004.md) — scheduler container and signals.

## Deliverables

- The runnable Compose stack and the configuration example.
- Passing static tests.
- Manual evidence for MAN-001 and MAN-003.

## Tests

- [x] UT-110 — Compose structure, healthcheck, ordering, no `env_file`.
- [x] IT-012 — `.env.example` ↔ `Settings` ↔ Compose, `${KEY-default}`, empty-value pass-through, secret scan with self-checks.
- [x] MAN-001 — one-command start ≤ 15 minutes; second `up`; `API_PORT=8001`.
- [x] MAN-003 — relevance sample of 50 jobs, at least 90%.

## Success Criteria

- MAN-001 evidence shows real jobs within 15 minutes of `docker compose up --build`.
