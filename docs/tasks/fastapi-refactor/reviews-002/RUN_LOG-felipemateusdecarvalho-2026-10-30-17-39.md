# RUN_LOG: cy-review-round, take-jobs v2 spec, round 2

- **User:** felipemateusdecarvalho
- **Date:** 2026-10-30 17:39 (America/Sao_Paulo)
- **Skills:** `cy-review-round`, with `cy-final-verify` for the closing checks
- **Slug:** `fastapi-refactor`
- **Scope:** spec artifacts only (no implementation exists): `_prd.md`, `_spec.md`, `_user_stories.md`, `_dx.md`, `_tests.md`, `adrs/adr-001.md` to `adr-005.md`, and the round-1 issues in `reviews-001/`.
- **Output:** status updates in `reviews-001/issue_001.md` to `issue_017.md`; new issues `reviews-002/issue_001.md` to `issue_004.md`.

## Request (relayed by the launching agent)

This round has two jobs:
- Verify each round-1 fix, and mark it `resolved` or reopen it to `pending` with evidence.
- Look for new problems introduced by the revision.

The recorded user decisions are authoritative: issue 001 (spawn child and DI seams), issue 004 (24 h start-up catch-up) and issue 014 (the v1 password is unused and must never be quoted). Do not edit spec artifacts, and do not access vagas.com or infojobs.com.br.

## Questions asked during this run

None. I asked the user no questions, and the user gave no answers during this run.

## Round-1 verdicts

- **Resolved (12):** 001, 002, 005, 006, 007, 008, 009, 011, 012, 013, 015, 017.
- **Reopened to `pending` (5):**
  - 003: the signal chain through the spawned crawl child.
  - 004: stale US-019.EC-3, MAN-001 and ADR-004 text.
  - 010: the FR-30 guard does not cover the spawn child; UT-115 expects the wrong exception class.
  - 014: the IT-012 scan fails on the repository's own artifacts.
  - 016: Sunday-first day-of-week ranges are rejected.

## New issues

- 001 (high): the report pipe is read after the child exits, which deadlocks every real-size crawl.
- 002 (medium): the O5 query counts today before its run finishes, capping the rate at 85.7%.
- 003 (low): the db healthcheck `$POSTGRES_USER` is interpolated by Compose.
- 004 (low): the CLI seams do not reach the scheduler tests or UT-073 and UT-077.

## Runtime checks performed (local only, no job-board access)

- Spawn `Pipe` hand-off with join before recv, on Python 3.13 (macOS and python:3.13-slim Linux). Backs new issue 001.
- Scrapy 2.19.0 in a spawn child against a slow 127.0.0.1 server: graceful-close time with one SIGTERM, and SIGINT plus SIGTERM. Backs the reopening of 003.
- APScheduler 3.11.3 `from_crontab` with `sun-thu` and `sun-sat`. Backs the reopening of 016.
- pytest-socket with `--allow-hosts`: the exception class, and spawn-child coverage. Backs the reopening of 010.
- postgres:16: the pinned O5 query with the IT-014 seed and with a no-run-yet today. Verifies 009 and backs new issue 002.
- Docker Compose 2.31.0 `config`: `${KEY-default}` rendering, empty-value pass-through, and the healthcheck interpolation. Verifies 012 and backs new issue 003.
- A script scanned the working tree for the v1 password without printing it, and found none. It also ran the IT-012 regexes over `docs/`. Backs the reopening of 014.

All temporary containers were removed, and the pulled python:3.13-slim image was deleted. Scratch files stayed in the session scratchpad.
