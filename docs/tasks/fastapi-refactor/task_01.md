---
status: completed
title: "Task 1: Foundation: tooling, package skeleton and settings"
type: chore
complexity: low
---

# Task 1: Foundation: tooling, package skeleton and settings

## Overview

This task sets up the v2 project skeleton that every other task builds on:
- a uv-managed Python 3.13 package `take_jobs` with ruff, import-linter, pytest and the network guard;
- a validated `Settings` object that reads every configuration key from the environment.

v1 is gone from the working tree (its deletion is already staged) and is preserved by commit `52018b3`.

## Shippable Outcome

- **Outcome:**
  - `uv sync` installs the project.
  - `uv run python -c "from take_jobs.config import Settings; Settings()"` loads every default from `_dx.md` › Config, and invalid values fail with the key named.
  - `uv run ruff check`, `uv run ruff format --check`, `uv run lint-imports` and `uv run pytest` all pass.
- **Verify in this task:** UT-020–UT-027 (config), UT-115 (session socket guard) and UT-118 (`SCRAPE_TERMS` slug rules).
- **Integration verification:** none.

## Requirements

- Python 3.13 via `.python-version`. Dependencies are declared in `pyproject.toml`, and `uv.lock` is committed to the tree (FR-28; `_spec.md` › Impact Analysis).
  - Runtime: fastapi, uvicorn[standard], sqlalchemy[asyncio], asyncpg, alembic, pydantic-settings, scrapy, apscheduler<4.
  - Dev: pytest, pytest-asyncio, pytest-cov, pytest-socket, httpx, ruff, import-linter, testcontainers[postgres], pyyaml.
- The import-linter contracts must encode `_spec.md` › Architectural Boundaries exactly. Packages that do not exist yet may be created as empty modules so the contracts resolve.
- Config follows `_spec.md` › Config Lifecycle and `_dx.md` › Config, with these rules:
  - comma-separated lists use `NoDecode` with a splitting validator;
  - validation fails fast with `Invalid configuration: <KEY>: <reason>` semantics, which the CLI maps to exit `2` in task_06;
  - `SCRAPE_CRON` is validated with `to_standard_crontab` + `CronTrigger.from_crontab` once task_02 provides the former. Until then, validate with `CronTrigger.from_crontab` directly, and task_02 switches the validator.
- The pytest configuration enables `pytest-socket` with `--disable-socket --allow-unix-socket` and allows loopback plus the testcontainers host (`_tests.md` › Strategy). The `integration` and `perf` markers are registered.
- `.gitignore` adds `.env`, `.venv`, `.ruff_cache`, `.coverage*` and `htmlcov/`, and drops the broken `../` lines.
- `src/take_jobs/__main__.py` calls `take_jobs.cli.main:main`. A minimal `main` returning `0` for `--help` is enough here; task_06 implements `collect`.

## Subtasks

- [x] 1.1 Rewrite `pyproject.toml` (deps, scripts `take-jobs = "take_jobs.cli.main:main"`, ruff, import-linter, pytest, coverage) and generate `uv.lock`.
- [x] 1.2 Create the package skeleton: `domain`, `application`, `infrastructure/db`, `infrastructure/scraping`, `api`, `cli`, `config.py` and `__main__.py`.
- [x] 1.3 Implement `Settings` with every key, default and validation rule.
- [x] 1.4 Configure pytest (asyncio mode, markers, socket guard) and write the config tests.
- [x] 1.5 Fix `.gitignore`.

## Implementation Details

See `_spec.md` › Architectural Boundaries, Config Lifecycle, Testing Approach and Build Order step 1.

### Relevant Files

- `pyproject.toml`, `.python-version` — draft from the interrupted start; rewrite.
- `.gitignore` — v1 file with broken `../` entries.
- `src/take_jobs/config.py` — new `Settings`.
- `src/take_jobs/__main__.py`, `src/take_jobs/cli/main.py` — entry points (minimal here).
- `tests/unit/test_config.py`, `tests/unit/test_socket_guard.py` — new.

### Dependent Files

- Every later task imports `take_jobs.config.Settings` and relies on these tool configurations.

### Related ADRs

- [ADR-001: Layered package with import-linter enforced boundaries](adrs/adr-001.md) — the contracts are written in this task.

## Deliverables

- A working uv project with a lockfile, import-linter contracts and pytest configuration.
- `Settings` with full validation.
- Passing tests UT-020–UT-027, UT-115 and UT-118.

## Tests

- [x] UT-020, UT-021, UT-022, UT-023, UT-024, UT-025, UT-026, UT-027 — `Settings` defaults, list parsing and validation.
- [x] UT-115 — the session socket guard raises `SocketConnectBlockedError` for a non-local host.
- [x] UT-118 — `SCRAPE_TERMS` slug rules: colliding slugs and slugs with no letters or digits fail naming `SCRAPE_TERMS`; the exact same term twice stays valid.

## Success Criteria

- `uv run ruff format --check && uv run ruff check && uv run lint-imports && uv run pytest` exits `0`.
