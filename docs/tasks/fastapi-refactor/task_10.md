---
status: completed
title: "Task 10: Delivery evidence: CI, README v1 → v2, `v1` tag and O5 query"
type: docs
complexity: low
---

# Task 10: Delivery evidence: CI, README v1 → v2, `v1` tag and O5 query

## Overview

This task makes the portfolio evidence visible and checkable:
- a GitHub Actions workflow that runs every gate;
- a rewritten README in English, with a "v1 → v2" section and the O5 success-rate query;
- the local `v1` tag on the last v1 commit;
- a test of the O5 query itself.

## Shippable Outcome

- **Outcome:**
  - `.github/workflows/ci.yml` runs format, lint, `lint-imports` and `pytest` with the 80% coverage gate on push and pull request.
  - The README's first screen shows the project, the CI badge and the one-command start, and it explains querying, configuration and "v1 → v2".
  - `git rev-parse v1^{commit}` is `52018b3…`.
  - The O5 query in the README returns the expected values.
- **Verify in this task:** UT-111–UT-114 (static contracts), IT-014 (O5 query), MAN-004 (green CI run on GitHub, after the user pushes), MAN-005 (tag, README sections, artifacts) and MAN-002 (O5 after 7 days of operation; post-delivery, recorded in the README and not gating).
- **Integration verification:** none.

## Requirements

- **CI:** `actions/checkout` with `fetch-depth: 0`, uv setup, `uv sync --frozen`, then `ruff format --check`, `ruff check`, `lint-imports` and `pytest --cov=take_jobs.domain --cov=take_jobs.application --cov-fail-under=80`. It runs on `ubuntu-latest`, where Docker is available.
- **README:**
  - sections for overview, running, querying the API, configuration and "v1 → v2";
  - the O5 SQL exactly as in `_spec.md` › Monitoring;
  - the "v1 → v2" section cites the v1 problems by file path only and **never quotes the v1 password**.
- **`v1` tag:** create it locally on `52018b3` (FR-32). **Do not push** the tag or the branch; that is the user's call.
- **O5 query:** keep it in `src/take_jobs/infrastructure/db/metrics.sql` (or as a constant), which both the README and IT-014 use.
- **MAN-004:** it can only complete after the user pushes. Record it as pending user action rather than blocking this task.

## Subtasks

- [x] 10.1 Write `.github/workflows/ci.yml`.
- [x] 10.2 Rewrite `README.md`, including the "v1 → v2" mapping and the O5 query.
- [x] 10.3 Create the local `v1` tag.
- [x] 10.4 Write UT-111–UT-114 and IT-014.
- [x] 10.5 Record MAN-005 evidence. Note MAN-002 and MAN-004 as post-delivery or user-dependent.

## Implementation Details

### Relevant Files

- `.github/workflows/ci.yml` — new.
- `README.md` — rewrite.
- `src/take_jobs/infrastructure/db/metrics.sql` — new.
- `tests/static/test_ci.py`, `tests/static/test_readme.py`, `tests/static/test_repo.py`, `tests/integration/test_o5_query.py` — new.

### Dependent Files

- Everything from tasks 01–09. The README describes the delivered system.

### Related ADRs

- [ADR-001](adrs/adr-001.md) — `lint-imports` gate in CI.

## Deliverables

- The CI workflow, the README, the `v1` tag and the O5 query with its test.

## Tests

- [x] UT-111 — CI workflow contract.
- [x] UT-112 — README headings, badge and O5 query.
- [x] UT-113 — `v1` tag.
- [x] UT-114 — SDD artifacts present.
- [x] IT-014 — O5 query (a) 71.4 and (b) 100.0.
- [ ] MAN-002 — O5 after 7 days (post-delivery).
- [x] MAN-004 — green CI on GitHub: runs 41167708543 (push) and 41167722942 (pull request) on PR #1.
- [x] MAN-005 — tag, README and artifacts check.

## Success Criteria

- The full local suite passes: `uv run ruff format --check && uv run ruff check && uv run lint-imports && uv run pytest --cov=take_jobs.domain --cov=take_jobs.application --cov-fail-under=80`.
