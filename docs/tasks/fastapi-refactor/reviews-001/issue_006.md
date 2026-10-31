---
provider: manual
pr:
round: 1
round_created_at: 2026-10-30T20:10:01Z
status: resolved
file: docs/tasks/fastapi-refactor/_dx.md
line: 327
severity: medium
author: claude-code
provider_ref:
---

# Issue 006: Run timeout not enforced on live crawl; takeover runs two crawlers

## Review Comment

**Problem.** `_dx.md` line 327 defines `SCRAPE_RUN_TIMEOUT_MINUTES` as the "Max duration of a run". No component enforces it on the live process. It only lets a *new* start mark the old row `failed`/`interrupted` (rule 13; `CollectionService.start_run`). Scrapy's defaults allow a single run to exceed 120 minutes:
- `DOWNLOAD_TIMEOUT` is 180 s and `RETRY_TIMES` is 2, so one request can take up to ~9 min;
- requests to a site are serialized (one slot per site);
- 12 terms × 9 min on a site that hangs is about 108 min, before robots.txt fetches and any slow but successful pages.

When that happens, a manual or startup `collect` marks the live run `interrupted` and starts a **second crawler against the same sites**. Two processes then each send 1 req/s, which breaks the PRD's scraping conduct and Safety Invariant 7. When the first process reaches `finish`, its conditional `UPDATE … WHERE status='running'` affects 0 rows and raises (Safety Invariant 2). That rolls back that run's whole ingestion.

**Suggested fix.**
- Enforce the bound inside the collector:
  - set Scrapy `CLOSESPIDER_TIMEOUT` below `SCRAPE_RUN_TIMEOUT_MINUTES` (e.g. timeout − 10 min), and map close reason `closespider_timeout` to a combination or run error;
  - set an explicit `DOWNLOAD_TIMEOUT` (e.g. 30 s) in `build_scrapy_settings`, and assert both in UT-048.
- Define the CLI outcome when `finish` affects 0 rows because the run was taken over (exit code and message).

## Triage

- Decision: `VALID`
- Notes: Root cause: the run timeout was only a takeover threshold; nothing bounded a live crawl.
- Fix applied (spec-only round, no code exists): _spec.md rule 25, Safety Invariants 2 and 9 (CLOSESPIDER_TIMEOUT = timeout - 10 min, DOWNLOAD_TIMEOUT 30 s), default timeout 60 (min 20), RunTakenOverError and CLI exit 1; _dx.md Config and Errors; UT-027, UT-048, UT-066, UT-105, UT-106.
- Verified (round 2): rule 25, Safety Invariants 2 and 9 (`CLOSESPIDER_TIMEOUT = (timeout − 10) × 60`, `DOWNLOAD_TIMEOUT = 30`), default timeout 60 with minimum 20 (UT-027), `RunTakenOverError` → exit 1 (UT-066, UT-105), UT-048 asserts both settings, UT-106 maps `closespider_timeout`. The claim that a live crawl ends before takeover depends on the child actually exiting; see reviews-002/issue_001 (pipe deadlock).
