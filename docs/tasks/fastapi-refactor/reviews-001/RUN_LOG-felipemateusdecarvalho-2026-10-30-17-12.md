# RUN_LOG: cy-review-round, take-jobs v2 spec, round 1

- **User:** felipemateusdecarvalho
- **Date:** 2026-10-30 17:12 (America/Sao_Paulo)
- **Skills:** `cy-review-round`, with `cy-final-verify` for the closing checks
- **Slug:** `fastapi-refactor`
- **Scope:** an independent review of the spec artifacts only (`_prd.md`, `_spec.md`, `_user_stories.md`, `_dx.md`, `_tests.md`, `adrs/adr-001.md` to `adrs/adr-005.md`). There is no implementation yet.
- **Output:** `reviews-001/issue_001.md` to `issue_017.md`

## Request (relayed by the launching agent)

Review the approved spec independently, without simply confirming it. Write evidence-backed issue files with severities under `reviews-001/`, and do not edit any spec artifact. Do not access vagas.com or infojobs.com.br. Treat the decisions recorded in the existing RUN_LOGs as authoritative.

## Questions asked during this run

None. I asked the user no questions, and the user gave no answers during this run.

## Runtime checks performed (no job-board access)

- APScheduler 3.11.3: the fire time computed after a restart, and the day-of-week semantics of `from_crontab`. Backs issues 004 and 016.
- Scrapy 2.19.0: a second `CrawlerProcess` in the same process, and `asyncio.run` inside a running loop. Backs issue 001.
- postgres:16: the spec's DDL, the ADR-005 expression without `coalesce`, the `xmax` upsert inside one transaction, and a varchar overflow inside the run transaction. Backs issues 002 and 013.
- Docker Compose 2.31.0: `${KEY:-default}` with empty values, and the `env_file` mapping form. Backs issue 012.
- python:3.13-slim: tzdata is present, so a suspected missing-tzdata finding was dropped. The image was removed afterwards.
