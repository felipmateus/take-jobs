# RUN_LOG — cy-fix-reviews — fastapi-refactor, review round 1

- **User:** felipemateusdecarvalho
- **Date:** 2026-10-30 17:25
- **Skill:** `cy-fix-reviews` (spec-only round; no code exists yet)
- **Scope:** `reviews-001/issue_001.md` … `issue_017.md` (3 high, 11 medium, 3 low)

## Questions asked and answers given

Asked before the skill started, during the triage of the reviewer's report. The answers define this run's scope.

| Question | User's answer |
| --- | --- |
| Issue 001: the Scrapy reactor does not restart in the same process, so the E2E tests cannot call `collect` twice. How should the crawl be isolated? (Crawl in a child process (Recommended) / E2E tests call the real CLI) | "Crawl em processo filho (Recommended)" |
| Issue 004: if the scheduler is off at 06:00 (e.g. laptop closed), that day's collection is lost. What should happen? (Collect if the last run is older than 24 h (Recommended) / Recover only within 1 h / Skip the missed collection) | "Coletar se a última tem +24h (Recommended)" |
| Issue 014: the v1 MySQL password remains in the public GitHub history, at the commit the `v1` tag will point to. Is it still used anywhere (database, account, other service)? (No longer used / Still used; I will change it) | "Não é mais usada" |
| Can the other 14 findings be applied with the fixes in the table? (Apply all (Recommended) / Exclude some) | "Aplicar todos (Recommended)" |
| Earlier: Do you want an independent review of the spec before generating the tasks? | "Sim, peça uma revisão independente da spec ao subagente reviewer antes de gerar as tasks." |

No further questions were asked during the skill run.

## What was done

- All 17 issues triaged as `valid`, each with its root cause and the fix applied in `## Triage`. None is marked `resolved`: the reviewer does that in the next round.
- Files changed: `_spec.md`, `_dx.md`, `_user_stories.md`, `_tests.md`, `adrs/adr-002.md`, `adrs/adr-004.md`, `adrs/adr-005.md`, `_prd.md` (FR-06 amendment, by the user's decision on issue 004).
- Main contract changes:
  - The crawl now runs in a `spawn` child process, with the DI seams `CliDeps`, `build_cli_deps`, `main(argv, deps=)` and `create_app(settings=, sources=)`.
  - New business rules 24–28: signal → `failed` with exit `4`; crawl time limit; ingest failure → `failed` with exit `1`; text sanitization; parse error fails only its combination.
  - The `SCRAPE_ON_EMPTY_DB` key is renamed `SCRAPE_ON_START`, adding the 24-hour catch-up. `SCRAPE_RUN_TIMEOUT_MINUTES` now defaults to 60.
  - Compose: `${KEY-default}`, no `env_file`, and an ordering, healthcheck and restart contract.
  - `collection_runs.expected_combinations` and a pinned O5 query.
  - New tests: UT-018, UT-019, UT-027, UT-037, UT-038, UT-049, UT-066, UT-067, UT-079, UT-085–UT-087, UT-104–UT-108, UT-110–UT-115, IT-013, IT-014. Revised: UT-017, UT-020, UT-032, UT-042, UT-048, UT-056–UT-058, UT-075, UT-080–UT-084, IT-003, IT-006–IT-009, IT-011, IT-012.

## Verification

- `check-spec-markers.py` with markers 4, 5 and 6 required → OK (5/5).
- `check-spec-part1-leak.py` → the same advisory hits as before (fixed user constraints, the no-migration decision, the credentials note, and a request count). All are justified.
- Cross-reference check: every test ID cited in the spec, ADRs and stories is defined in `_tests.md`; every defined ID is in the coverage matrix, directly or within a component range; all 33 FRs are referenced in `_user_stories.md`.
- `cy-final-verify` product checks (lint, tests) do not apply: no code exists yet.
- Nothing was committed.
