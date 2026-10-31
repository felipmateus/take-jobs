---
provider: manual
pr:
round: 1
round_created_at: 2026-10-30T20:10:01Z
status: resolved
file: docs/tasks/fastapi-refactor/_spec.md
line: 577
severity: low
author: claude-code
provider_ref:
---

# Issue 017: Impact Analysis omits uv.lock and take_jobs/__main__.py

## Review Comment

**Problem.** The design depends on two files that are absent from the Impact Analysis inventory (lines 577–591) and from the Build Order:
- `uv.lock`. CI runs `uv sync --frozen` (line 633), which fails when no lockfile is committed. The Dockerfile presumably relies on it too.
- `src/take_jobs/__main__.py`. The scheduler launches `[sys.executable, "-m", "take_jobs", "collect", …]` (Safety Invariant 6, ADR-004, UT-084), which needs a package `__main__` delegating to `take_jobs.cli.main:main`. Only the `take-jobs` console script is specified.

**Suggested fix.**
- Add both files to the Impact Analysis table and to Build Order step 1 (`uv lock` committed; `__main__.py` calls `raise SystemExit(main())`).
- Add an assertion, for example in UT-084 or a small UT, that `python -m take_jobs --help` exits `0`.

## Triage

- Decision: `VALID`
- Notes: Root cause: the inventory omitted files the design depends on.
- Fix applied (spec-only round, no code exists): _spec.md Impact Analysis rows for uv.lock and src/take_jobs/__main__.py, Build Order step 1, Architectural Boundaries note; UT-086.
- Verified (round 2): Impact Analysis rows for `uv.lock` and `src/take_jobs/__main__.py`, Build Order step 1, the Architectural Boundaries note with the exact `__main__.py` body, and UT-086 (`python -m take_jobs --help` exits 0).
