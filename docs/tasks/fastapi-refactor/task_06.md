---
status: completed
title: "Task 6: CLI `take-jobs collect` with signal-safe run lifecycle"
type: feature
complexity: critical
---

# Task 6: CLI `take-jobs collect` with signal-safe run lifecycle

## Overview

This task delivers the collector command. `take-jobs collect` starts a run, crawls in the spawned child, ingests, and reports through human or `--json` output with exit codes 0, 1, 2, 3 and 4. It is the composition root for processes (`CliDeps`, `build_cli_deps`). It also owns the signal-safe lifecycle that keeps a run from ever being left `running` or misreported.

## Shippable Outcome

- **Outcome:** `uv run take-jobs collect` against a database and fixture-backed sources:
  - collects, stores and prints the `_dx.md` output;
  - a stop (SIGTERM or Ctrl+C) at any phase from `start_run` on records `interrupted by signal` and exits `4` within 12 seconds;
  - a late signal keeps the run's own code;
  - invalid config exits `2`, a concurrent run exits `3`, and crashes or ingest failures exit `1`.
- **Verify in this task:**
  - UT-070–UT-079, UT-104, UT-105 and UT-117 (fakes through `deps`);
  - IT-007 (two full collects in one process: reactor isolation and pickling);
  - IT-009 (exit codes with a real database);
  - IT-013 (signals in crawl, Ctrl+C and ingest).
- **Integration verification:** E2E-001–E2E-004 in task_07 drive this command.

## Requirements

- **Seams:** `CliDeps`, `build_cli_deps(settings, sources, *, child_initializer=None)` and `main(argv=None, *, deps=None)`, per `_spec.md` › Core Interfaces. `deps=None` builds them from `Settings()`, and a configuration error exits `2`.
- **Data flow:** steps 1–5 in `_spec.md` › System Architecture, exactly:
  - **One handler:** a single process-wide `signal.signal` handler for the command; never `loop.add_signal_handler`.
  - **Flag only:** `start_run` and every `fail_run` are flag-only.
  - **Cancellable ingestion:** `complete_run` can be cancelled only while `cancellable` is set, and the CLI passes `before_commit=phase.clear_cancellable`.
  - **Flag check:** after the non-terminal phases (`start_run`, crawl).
  - **Re-read:** after `CancelledError`, re-read the run with `get_run`.
  - **"Taken over" message:** only when `complete_run` itself raises `RunTakenOverError`.
  - **Restore:** the original handlers on return.
- **Messages and exit codes:** exactly as in `_dx.md` › CLI and Errors.
- **Database engines:** every phase opens a fresh engine (Safety Invariant 5), with a 5-second connect timeout.
- **Docker:** IT-007, IT-009 and IT-013 need it. If Docker is unavailable, stop and report.

## Subtasks

- [x] 6.1 Implement `cli/main.py`: argparse (`collect --trigger --json`), `CliDeps`, `build_cli_deps`.
- [x] 6.2 Implement the collect flow, with the phase reference, signal handler, flag checks, re-read and output formatting.
- [x] 6.3 Write the unit tests with fakes (UT-070–UT-079, UT-104, UT-105, UT-117).
- [x] 6.4 Write the integration tests with the fixture server and real database (IT-007, IT-009, IT-013), using `child_initializer=install_test_socket_guard`.

## Implementation Details

### Relevant Files

- `src/take_jobs/cli/main.py`, `src/take_jobs/cli/collect.py` — new.
- `tests/unit/cli/test_collect.py`, `tests/integration/test_collect_cli.py`, `tests/integration/test_signals.py` — new.

### Dependent Files

- `src/take_jobs/application/services.py` (task_05), `src/take_jobs/infrastructure/scraping/scraper.py` (task_04), `src/take_jobs/infrastructure/db/*` (task_03).
- `tests/support/{socket_guard,fixture_server}.py` (task_04), `tests/fakes.py` (task_05).

### Related ADRs

- [ADR-002](adrs/adr-002.md) — failure paths and signal handling.

## Deliverables

- The `take-jobs collect` command with all exit codes.
- Passing unit and integration tests.

## Tests

- [x] UT-070–UT-079 — output, exit codes, configuration, composition, ingest failure.
- [x] UT-104, UT-105 — exit `4` on interruption; the "taken over" message.
- [x] UT-117 — the single handler across phases, `start_run`/after-commit/terminal `fail_run` cases.
- [x] IT-007 — two collects in one process.
- [x] IT-009 — exit `3`, and stale-run takeover.
- [x] IT-013 — signals (a) during the crawl, (b) Ctrl+C, (c) during ingestion.

## Success Criteria

- IT-013 shows exit `4` within 12 seconds in every variant, and no crawl child is left alive.
