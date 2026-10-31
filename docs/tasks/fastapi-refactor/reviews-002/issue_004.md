---
provider: manual
pr:
round: 2
round_created_at: 2026-10-30T20:39:57Z
status: resolved
file: docs/tasks/fastapi-refactor/_spec.md
line: 540
severity: low
author: claude-code
provider_ref:
---

# Issue 004: CLI seams don't reach the scheduler tests or UT-073/UT-077

## Review Comment

**Problem.** The revision added `CliDeps`, `build_cli_deps` and `main(argv, *, deps=)` as the CLI test seams (`_spec.md` › Core Interfaces, lines 539–551). Several revised test cases still cannot be written against them as specified:

1. **Scheduler (UT-080 to UT-087).**
   - `CliDeps` has a `runner`, but no seam for the probe-retry sleeper (UT-085, "a fake sleeper"), the clock (UT-080 and UT-081, "25 h ago" and "3 h ago"), or the scheduler object.
   - `main(["scheduler"], deps=…)` ends in `BlockingScheduler.start()`, which never returns. UT-080 ("runner called … before the scheduler loop starts") and UT-083 ("after setup, the scheduler has exactly one job") therefore need an unspecified way to build the scheduler without starting it.
   - UT-087 needs the SIGTERM handler as a callable.
   The implementer has to invent these seams, as round 1 issue 001 found for `collect`.
2. **CLI preamble vs UT-073 and UT-077.**
   - `_tests.md` line 255 says "All CLI cases call `main([...], deps=CliDeps(...))`". UT-073 (env `SCRAPE_TERMS=""` → exit `2`) can only pass with `deps=None`, because a pre-built `CliDeps` already holds a valid `Settings`.
   - UT-077 asserts on the `RelevancePolicy` and the scraper terms that `build_cli_deps` produces. `CliDeps` exposes neither: the policy is hidden inside `open_collection_service`.
3. **`create_app(settings=…)` vs the DI chain.** DI step 1 is "`get_settings` (cached)". If that is a process-global cache of `Settings()`, the request-time dependencies and the lifespan engine ignore the `settings` passed to `create_app`. The E2E tests (`create_app(settings, sources)` against the testcontainers database) then query the wrong database.

**Suggested fix.**
- Add a scheduler seam to Core Interfaces, for example `build_scheduler(settings, runner, *, clock, sleep) -> BaseScheduler` plus `run_startup(service, runner, *, sleep)`, or the same fields on `CliDeps`. Name the SIGTERM handler factory.
- Reword the `_tests.md` CLI preamble to allow `deps=None` for UT-073, and make UT-077 test `build_cli_deps` directly through observable fields.
- State that `get_settings` reads `request.app.state.settings`, which `create_app` sets.

## Triage

- Decision: `VALID`
- Notes: Root cause: CliDeps lacked the scheduler, clock and sleep seams; the CLI test preamble conflicted with UT-073/UT-077; get_settings was described as a global cache.
- Fix applied (spec-only round, no code exists): _spec.md Core Interfaces: CliDeps gains relevance, clock, sleep and scheduler_factory; take_jobs.cli.scheduler seams wait_for_database, run_startup, configure_scheduler, make_shutdown_handler and run_scheduler; the DI chain step 1 reads request.app.state.settings. _tests.md: the CLI preamble names the UT-073 and UT-077 exceptions; UT-077 tests build_cli_deps via deps.relevance and settings; a scheduler preamble is added; UT-085 and UT-087 are rewritten against the seams.
- Verified (round 3, 2026-10-30): `CliDeps` now has `relevance`, `clock`, `sleep` and `scheduler_factory`; `take_jobs.cli.scheduler` names `wait_for_database`, `run_startup`, `configure_scheduler`, `make_shutdown_handler` and `run_scheduler`; the CLI preamble names the UT-073/UT-077 exceptions; UT-077 asserts through `deps.relevance`; DI step 1 reads `request.app.state.settings`. UT-083 was checked against a never-started APScheduler 3.11.3 `BackgroundScheduler`. Two remaining gaps are tracked elsewhere: the probe contract (new round-3 issue 001) and the order of `run_scheduler` (reopened round-1 issue 003).
