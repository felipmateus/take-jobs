---
provider: manual
pr:
round: 1
round_created_at: 2026-10-30T20:10:01Z
status: resolved
file: docs/tasks/fastapi-refactor/adrs/adr-005.md
line: 18
severity: medium
author: claude-code
provider_ref:
---

# Issue 013: ADR-005 search_text has no coalesce: null company hides the job

## Review Comment

**Problem.** ADR-005 line 18 defines the generated column as `immutable_unaccent(lower(title || ' ' || company || ' ' || description))`. `_spec.md` line 476 wraps both nullable columns in `coalesce(…, '')`. In PostgreSQL, `text || NULL` is `NULL`. An implementer following the accepted ADR therefore produces `search_text IS NULL` for every job missing a company or a description: US-001.EC-2 explicitly allows those nulls. Such jobs never match any `q`. IT-003 seeds complete rows, so the gap would pass the tests.

**Runtime evidence** (postgres:16, both variants side by side, job with only a title):
```
          search_text          | adr_variant_is_null
 desenvolvedor python senior   | t
```
(The spec's variant also checked out: the `IMMUTABLE` wrapper over `public.unaccent('public.unaccent'::regdictionary, $1)` is accepted in a stored generated column, and the GIN `gin_trgm_ops` index builds on it.)

**Suggested fix.**
- Align ADR-005 with the spec's `coalesce` expression.
- Add an IT-003 case: a job with `company = NULL` and `description = NULL` is still found by a title `q`.

## Triage

- Decision: `VALID`
- Notes: Root cause: ADR-005 omitted coalesce, which the spec had.
- Fix applied (spec-only round, no code exists): ADR-005 Decision aligned with _spec.md; IT-003 case for a null company and description.
- Verified (round 2): ADR-005 Decision now uses the same `coalesce` expression as `_spec.md` › Data Models; IT-003 adds the title-only job found by `q="rust"`.
