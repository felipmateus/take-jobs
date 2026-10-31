---
provider: manual
pr:
round: 1
round_created_at: 2026-10-30T20:10:01Z
status: resolved
file: docs/tasks/fastapi-refactor/adrs/adr-005.md
line: 55
severity: low
author: claude-code
provider_ref:
---

# Issue 015: ADR-005 says IT-011 covers <3-char queries; IT-011 excludes them

## Review Comment

**Problem.** The ADR-005 risk (line 55) says queries shorter than 3 characters "fall back to a scan" and are "covered by the performance check IT-011". IT-011 (`_tests.md` line 303) explicitly runs only searches with "`q` (≥ 3 characters)". So the case the ADR claims is covered is never measured against O7.

With `gin_trgm_ops`, a 1–2 character `LIKE '%xy%'` extracts no trigrams. The planner may still choose a full GIN index scan and recheck all 50k rows, and such short terms (for example `q=go`, `q=js`, `q=ui`) are realistic developer searches.

**Suggested fix.** Add 1- and 2-character queries (e.g. `go`, `js`) to IT-011's query mix, asserting the p95 for them too. Otherwise, re-word the ADR risk so it no longer claims coverage, and bound the case another way (for example a documented `q` minimum length).

## Triage

- Decision: `VALID`
- Notes: Root cause: ADR-005 claimed IT-011 coverage for queries under 3 characters that IT-011 excluded.
- Fix applied (spec-only round, no code exists): IT-011 adds a separate 1-2 character query set with its own p95 assertion; ADR-005 risk reworded with an escalation rule.
- Verified (round 2): IT-011 adds a separate 1–2 character query set (`go`, `js`, `ui`, `c`) with its own p95 assertion; ADR-005 Risks reworded with an escalation to the user instead of a coverage claim.
