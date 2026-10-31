---
provider: manual
pr:
round: 5
round_created_at: 2026-10-30T22:33:23Z
status: resolved
file: docs/tasks/fastapi-refactor/_spec.md
line: 256
severity: low
author: claude-code
provider_ref:
---

# Issue 002: Stop-flag check after a terminal phase contradicts late-signal rule

## Review Comment

**Problem.** Round 4 made every `fail_run` flag-only (`_spec.md` line 249): a signal during the crash or ingest-failure `fail_run` now sets `stop_requested` and lets the phase finish. That creates a path the post-phase rule handles in two contradictory ways:

- Line 256: "**After every phase,** the CLI checks `stop_requested`. If it is set, the CLI skips the remaining phases, records `interrupted by signal` and exits `4`." Safety Invariant 8 (line 969) repeats "checks the stop flag after every phase".
- Lines 123 and 257: a signal after the run has finished does not change it; the CLI logs `signal_after_finish` and exits with the run's normal code.
- Failure-path table, line 284: "A signal arrives at any step after 2 (rule 24) → `interrupted by signal`, `4`". This row still says "after 2", while rule 24 (line 117) now says "from `start_run` on", and it also covers step 4 after commit and step 5, where the late-signal rule applies.

**Failure mode.** The crawl crashes, the CLI enters `fail_run(run_id, "<crash message>")`, and SIGTERM arrives during it (the scheduler stopping, or Ctrl+C). The run is now `failed`. Taken literally, line 256 makes the CLI call `fail_run(run_id, "interrupted by signal")` again; its conditional `UPDATE` affects 0 rows and raises `RunTakenOverError` (Safety Invariant 2). Line 261 says the "taken over" message is printed only for `complete_run`'s own `RunTakenOverError`, so this exception has no specified handling: an unhandled traceback, a wrong "taken over" message, or exit `4` are all plausible implementations. The same literal reading is what UT-117's "After commit" case (`_tests.md` line 305) has to override for `complete_run`; nothing covers the terminal `fail_run` case.

**Suggested fix.**
- Scope the post-phase check: it applies only after `start_run` and after the crawl, i.e. while the run is known to be `running`. After `complete_run` returns or a terminal `fail_run` returns, a set flag means a late signal: log `signal_after_finish` and keep that phase's exit code (`1` for crash/ingest failure).
- Update the failure-path table row to "from step 2 on, while the run is running" and align Safety Invariant 8's wording.
- Add a UT-117 case: the scraper raises `ScrapeCrashedError("boom")`, the handler is invoked inside the fake `fail_run` → `fail_run` is called once, stderr `Collection run 1 failed: boom`, `signal_after_finish` logged, exit `1`.

## Triage

- Decision: `VALID`
- Notes: Root cause: the post-phase stop-flag check was stated for every phase, contradicting the late-signal rule after terminal phases (which now include the flag-only fail_run).
- Fix applied (spec-only round, no code exists): _spec.md data flow step 1: the check applies after the non-terminal phases (`start_run`, crawl); after a terminal phase a set flag only logs `signal_after_finish` and keeps the exit code, and fail_run is never called twice. Failure-path table rows split into 'from step 2 on, while running' and 'after a terminal phase'; rule 24 bullet and Safety Invariant 8 aligned; ADR-002 aligned. New UT-117 case: a signal during the crash fail_run → fail_run is called once, exit 1.
- Verified (round 6): the post-phase check is scoped to non-terminal phases in data flow step 1 (lines 256-257: after `start_run` and the crawl only; after a terminal phase a set flag logs `signal_after_finish`, keeps the exit code, and `fail_run` is never called twice). Rule 24 (line 123), the failure-path table (lines 284, 286: 'from step 2 on, while the run is still `running`' / 'after a terminal phase'), Safety Invariant 8 (line 975) and ADR-002 line 44 agree. UT-117 (`_tests.md` line 306) adds the signal-during-crash-`fail_run` case: one `fail_run`, stderr `Collection run 1 failed: boom`, `signal_after_finish`, exit `1`, no `RunTakenOverError`.
