---
status: completed
title: "Task 2: Domain model, ports and business rules"
type: feature
complexity: medium
---

# Task 2: Domain model, ports and business rules

## Overview

This task implements the pure domain layer: the entities, the value objects, the ports (`Protocol`s), the domain errors and every business rule that needs no I/O. Those rules are normalization, relevance, seniority, activity, final run status, the startup collection reason and standard-cron day-of-week handling. Every later layer depends on these types and rules.

## Shippable Outcome

- **Outcome:** `take_jobs.domain` exposes the types, ports, errors and rules defined in `_spec.md` › Core Interfaces (`models.py`, `ports.py`, `rules.py`, `errors.py`). The rules behave exactly as Business Rules 4–15 state.
- **Verify in this task:** UT-001–UT-019.
- **Integration verification:** none.

## Requirements

- The domain imports only the standard library (ADR-001, `lint-imports`).
- The relevance and seniority keyword semantics are Business Rules 4–8, with the default lists from `_dx.md` › Config.
- `to_standard_crontab` expands the day-of-week field into an explicit Sunday-first list of names (Config Lifecycle). After this task, the `Settings` cron validator from task_01 uses it.
- The ports include `UnitOfWork.probe`, `JobScraper.interrupt()` and `CollectionRunRepository.latest_finished()`/`start(..., expected_combinations)`, with `finish` raising `RunTakenOverError`.
- `RunTotals.from_results`, and `CollectionRun.totals` as a stored field.

## Subtasks

- [x] 2.1 Implement `models.py`: enums, dataclasses, `Page`, `RunTotals`, `Job.is_active`.
- [x] 2.2 Implement `ports.py` and `errors.py`.
- [x] 2.3 Implement `rules.py`: `normalize`, `RelevancePolicy`, `classify_seniority`, `final_run_status`, `startup_collection_reason`, `to_standard_crontab`.
- [x] 2.4 Switch the `Settings` cron validator to `to_standard_crontab`.
- [x] 2.5 Write the unit tests.

## Implementation Details

### Relevant Files

- `src/take_jobs/domain/{models,ports,rules,errors}.py` — new.
- `src/take_jobs/config.py` — cron validator update.
- `tests/unit/domain/test_rules.py`, `tests/unit/domain/test_models.py` — new.

### Dependent Files

- Tasks 03–08 import these types and ports.

### Related ADRs

- [ADR-001](adrs/adr-001.md) — the domain has no framework imports.

## Deliverables

- The domain package with full rule coverage.

## Tests

- [x] UT-001–UT-013 — normalization, relevance and seniority.
- [x] UT-014–UT-017 — activity, run status, `Page`, `RunTotals`.
- [x] UT-018 — `startup_collection_reason`.
- [x] UT-019 — `to_standard_crontab`.

## Success Criteria

- Domain and application coverage contribute toward the 80% gate; this task's modules are at least 90% covered.
