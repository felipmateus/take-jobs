---
provider: manual
pr:
round: 1
round_created_at: 2026-10-30T20:10:01Z
status: resolved
file: docs/tasks/fastapi-refactor/_spec.md
line: 615
severity: medium
author: claude-code
provider_ref:
---

# Issue 012: Compose `${KEY:-default}` blocks an empty exclude list; env_file invalid

## Review Comment

**Problem 1: contract conflict.** Rule 6 and `_dx.md` › Config say `RELEVANCE_EXCLUDE_KEYWORDS` "may be empty", and UT-022 asserts that an empty value gives a valid empty list. But Config Lifecycle (line 615) requires every key in `docker-compose.yml` to use `${KEY:-default}`, and IT-012 enforces that. In Compose, `:-` substitutes the default when the variable is unset **or empty**. Under Compose, the documented path (copy `.env.example` to `.env` and edit), a maintainer can therefore never empty the exclude list. Setting `SCRAPE_TERMS=` likewise silently falls back to the defaults instead of failing with exit `2` (US-003.EC-3 and US-020 hold only outside Compose).

**Problem 2: invalid YAML contract.** The spec writes `env_file: {path: .env, required: false}`. Compose rejects a single mapping. The long syntax is a list.

**Runtime evidence** (Docker Compose 2.31.0, `.env` containing `RELEVANCE_EXCLUDE_KEYWORDS=` and `SCRAPE_TERMS=`):
```
services.scheduler.env_file must be a string          # mapping form, exit 15
# after changing it to env_file: [{path: .env, required: false}]
RELEVANCE_EXCLUDE_KEYWORDS: cnc,torno                 # empty value replaced by default
SCRAPE_TERMS: desenvolvedor
```

**Suggested fix.**
- Use `${RELEVANCE_EXCLUDE_KEYWORDS-default}` (no colon: default only when unset) for keys where empty is meaningful, and say so in Config Lifecycle. Adjust IT-012's "`${KEY:-default}`" assertion to match.
- Write the long syntax as `env_file: [{path: .env, required: false}]`.
- Optionally drop `env_file` altogether. Compose already reads the project `.env` for interpolation, and every key is listed under `environment:`.

## Triage

- Decision: `VALID`
- Notes: Root cause: ${KEY:-default} substitutes empty values, and the env_file mapping syntax is invalid.
- Fix applied (spec-only round, no code exists): _spec.md Config Lifecycle: ${KEY-default} for every key, no env_file; _dx.md Config note; US-020.EC-4; IT-012 updated; Docker Compose assumption changed to >= 2.20.
- Verified (round 2): Config Lifecycle uses `${KEY-default}` with no `env_file:`; `_dx.md` Config note, US-020.EC-4, IT-012 updated. Runtime (Docker Compose 2.31.0): with `.env` holding `RELEVANCE_EXCLUDE_KEYWORDS=` and `SCRAPE_TERMS=`, `docker compose config` renders both as `""`; with no `.env`, the defaults (including `SCRAPE_USER_AGENT`, `SCRAPE_CRON`, `DATABASE_URL`) render verbatim.
