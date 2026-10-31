---
provider: manual
pr:
round: 2
round_created_at: 2026-10-30T20:39:57Z
status: resolved
file: docs/tasks/fastapi-refactor/_spec.md
line: 263
severity: low
author: claude-code
provider_ref:
---

# Issue 003: db healthcheck `$POSTGRES_USER` is interpolated by Compose, not shell

## Review Comment

**Problem.** The Compose contract (`_spec.md` › System Architecture, line 263) gives the `db` healthcheck as `pg_isready -U $POSTGRES_USER -d $POSTGRES_DB`. In `docker-compose.yml`, Compose interpolates `$VAR` at parse time from the shell and `.env`, not from the container's environment. On the Golden Path, with no `.env` and no exported variables, both variables are unset. So every `docker compose` command prints warnings, and the healthcheck runs with empty arguments. This also conflicts with Config Lifecycle and IT-012, which say that every key appears in `docker-compose.yml` as `${KEY-default}`.

**Runtime evidence** (Docker Compose 2.31.0, `env -i … docker compose config`, with no `.env`, on a file that follows the contract):
```
level=warning msg="The \"POSTGRES_USER\" variable is not set. Defaulting to a blank string."
level=warning msg="The \"POSTGRES_DB\" variable is not set. Defaulting to a blank string."
        - 'pg_isready -U  -d '
```
`pg_isready -U -d` parses `-d` as the user name. The check still reports "accepting connections", so ordering works by accident. The evaluator's first `docker compose up --build` shows warnings, though, which the `_dx.md` Golden Path output does not show.

**Suggested fix.** Write the healthcheck so the container's shell expands the variables: `["CMD-SHELL", "pg_isready -U $$POSTGRES_USER -d $$POSTGRES_DB"]`, or use `${POSTGRES_USER-take_jobs}`. Add a UT-110 assertion that the rendered healthcheck has non-empty `-U` and `-d` arguments.

## Triage

- Decision: `VALID`
- Notes: Root cause: Compose interpolates $VAR in the healthcheck at parse time.
- Fix applied (spec-only round, no code exists): _spec.md Compose contract: healthcheck ["CMD-SHELL", "pg_isready -U $$POSTGRES_USER -d $$POSTGRES_DB"], and db environment uses ${POSTGRES_USER-take_jobs} etc. UT-110 asserts the raw $$ form and, when docker is available, no warnings and non-empty arguments.
- Verified (round 3, 2026-10-30): the Compose contract uses `["CMD-SHELL", "pg_isready -U $$POSTGRES_USER -d $$POSTGRES_DB"]`, and the db `environment:` sets `POSTGRES_USER: ${POSTGRES_USER-take_jobs}` etc., so the container shell expands non-empty values. UT-110 asserts the raw `$$` form. `docker compose config` was not run (daemon unavailable; per instructions).
