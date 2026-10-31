---
provider: manual
pr:
round: 1
round_created_at: 2026-10-30T20:10:01Z
status: resolved
file: docs/tasks/fastapi-refactor/_spec.md
line: 196
severity: medium
author: claude-code
provider_ref:
---

# Issue 011: Compose startup order and scheduler behavior when DB isn't ready

## Review Comment

**Problem.** The Golden Path (`_dx.md` lines 14–25) shows `db` Healthy, then `migrate` Exited (0), and only then `api` and `scheduler` starting. No artifact defines that contract:
- `depends_on` with `condition: service_healthy` for `db` and `service_completed_successfully` for `migrate`;
- a `db` healthcheck (`pg_isready`);
- restart policies.

The scheduler also has no defined behavior when `JobStoreProbe.is_empty()` fails at start (ADR-004 line 24; UT-080–UT-082 cover only empty and non-empty). Without the ordering, the scheduler can probe before the migration ran (`relation "jobs" does not exist`) or before PostgreSQL accepts connections. The outcome is then up to the implementer: crash, skip the startup run, or retry. Two of those outcomes lose FR-06's startup collection and break O4.

**Suggested fix.**
- Add a Compose contract to `_spec.md` › System Architecture or `_dx.md`:
  - a `db` healthcheck;
  - `migrate` depends on `db: service_healthy`;
  - `api` and `scheduler` depend on `migrate: service_completed_successfully`;
  - `restart: unless-stopped` for `api` and `scheduler`.
- Specify the scheduler's startup behavior when the probe fails: retry with backoff up to N seconds, then exit non-zero, and log `startup_probe_failed`.
- Add a UT for it, and extend IT-012 (or the FR-27 static test) to assert the `depends_on` conditions.

## Triage

- Decision: `VALID`
- Notes: Root cause: no Compose ordering contract, and no scheduler behavior when the database is not ready.
- Fix applied (spec-only round, no code exists): _spec.md Compose contract table and scheduler start-up probe retry; ADR-004; US-004.EC-3, US-019.AC-1; UT-085, UT-110.
- Verified (round 2): Compose contract table (db healthcheck, `migrate` on `service_healthy`, `api`/`scheduler` on `service_completed_successfully`, restart policies, `init`, `stop_grace_period`), the scheduler start-up probe retry and exit 1, US-004.EC-3, UT-085 and UT-110. `${KEY-default}` with the long defaults renders correctly in `docker compose config` (2.31.0). A defect in the healthcheck command string is tracked as reviews-002/issue_003.
