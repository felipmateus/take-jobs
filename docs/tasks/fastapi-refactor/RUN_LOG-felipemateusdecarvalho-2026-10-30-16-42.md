# RUN_LOG — cy-create-spec — take-jobs v2

- **User:** felipemateusdecarvalho
- **Date:** 2026-10-30 16:42
- **Skill:** `cy-create-spec` (with `cy-spec-preflight` checks)
- **Slug:** `fastapi-refactor`
- **Input:** [`_prd.md`](_prd.md) and the decisions in [`RUN_LOG-felipemateusdecarvalho-2026-10-30-16-21.md`](RUN_LOG-felipemateusdecarvalho-2026-10-30-16-21.md)

## Request

**User:** "Sim, crie a tech spec com cy-create-spec a partir do _prd.md."

## Questions asked during this run

None. The skill's product checkpoint was already satisfied by the PRD interview (grilling, 21 decisions confirmed by the user), so the interview was not repeated. Technical decisions that the evidence could settle were made in the spec and are listed below for the user's review. One item is left open for the user (OQ-1).

## Decisions made by the spec (pending user approval of the spec)

| Decision | Where |
| --- | --- |
| One package `take_jobs` with layers domain / application / infrastructure / api / cli, with boundaries enforced by import-linter | ADR-001 |
| Collection runs in three phases (start → crawl → ingest); Scrapy never touches the database | ADR-002 |
| One spider per source walking all terms, to guarantee 1 req/s per site | ADR-003 |
| APScheduler container launching `take-jobs collect` as a subprocess (no shell) | ADR-004 |
| Accent-insensitive search with `unaccent` + `pg_trgm` generated column | ADR-005 |
| Job identity = source + site's job id (not URL or title) | Spec › Business Rule 1 |
| Activity computed at read time; no stored flag | Spec › Key Decisions |
| Single running run enforced by a partial unique index; stale runs (> 120 min) marked `interrupted` | Spec › Rule 13, Safety Invariants |
| Per-combination results in a side table, not JSONB | Spec › Key Decisions |
| Default relevance include/exclude keyword lists and seniority keyword table | Spec › Business Rules 6–8; `_dx.md` › Config |
| API without version prefix; `size` max 100; `q` max 100 chars; unified error shape | Spec › Key Decisions; `_dx.md` › Errors |
| CLI exit codes 0/1/2/3 and `--json` output | `_dx.md` › CLI |
| No `.env` needed: Compose defaults; DB port not published; `SCRAPE_DOWNLOAD_DELAY` ≥ 1.0 enforced | `_dx.md` › Config; Spec › Config Lifecycle |

## Open question for the user

- **OQ-1 — User-Agent identity.** Default to an honest bot UA (`take-jobs/2.0 (+repo URL)`). If the fixture-capture task shows the sites blocking it, return to the user before switching to a browser UA.

## Preflight results

- `check-spec-markers.py` with `--require 4-data-model-rationale --require 5-side-table-vs-json --require 6-numbered-invariants` → OK, 5/5. The first run flagged marker 5 as missing; the side-table rationale was added to Key Decisions.
- `check-spec-part1-leak.py` → 6 advisory hits, all justified and kept:
  - PostgreSQL and WebSocket are fixed user constraints and non-goals.
  - MySQL refers to the user's no-migration decision.
  - "480" is a request count, not a status code.
  - "403" is observed site behavior cited as evidence in OQ-1.
- Cross-reference check: every test ID cited in the spec, ADRs and stories is defined in `_tests.md`, and every user story has a coverage-matrix row. Component rows for CLI, scheduler and API were added after the first check.

## Spec approval

**Question:** Você aprova a spec como está?
**User's answer:** "Aprovo a spec, incluindo a recomendação do OQ-1 (User-Agent honesto)."

Applied: `_spec.md` status set to Approved, OQ-1 marked resolved, ADR-001 to ADR-005 set to Accepted.

## Artifacts produced

- `_spec.md` (Part I product + Part II technical)
- `_user_stories.md` (US-001–US-022)
- `_dx.md` (CLI, HTTP API, Config, Errors)
- `_tests.md` (UT-001–UT-103, IT-001–IT-012, E2E-001–E2E-005, MAN-001–MAN-005)
- `adrs/adr-001.md` … `adrs/adr-005.md`
