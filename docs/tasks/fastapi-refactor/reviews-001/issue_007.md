---
provider: manual
pr:
round: 1
round_created_at: 2026-10-30T20:10:01Z
status: resolved
file: docs/tasks/fastapi-refactor/adrs/adr-002.md
line: 71
severity: medium
author: claude-code
provider_ref:
---

# Issue 007: Parser exceptions stop a term but it is still recorded as success

## Review Comment

**Problem.** Errors are mapped to combinations only through request errbacks: UT-045 covers `HttpError` and UT-047 covers `IgnoreRequest` from robots.txt. In Scrapy, an exception raised inside a **callback** (for example, `parse_listing` hitting an `AttributeError` after a site HTML change) does not reach the request's errback. Scrapy logs "Spider error processing", fires `spider_error`, and the term's pagination simply stops.

ADR-002 line 71 leaves the implementer free to choose "`item_scraped` and `spider_error` signals, **or** spider-held per-term state". With the second option, a parser crash is invisible: the combination is recorded `success` with the pages reached. That is the failure the run history must surface (US-005, the evaluator's "what failed"), and it inflates O5.

No test covers a callback exception. US-005.EC-4 (HTML changed → 0 cards → success) is a different case.

**Suggested fix.**
- Make `spider_error` handling mandatory in ADR-002: the error is attributed to `response.meta["term"]` and recorded as `"parse error: <ExceptionType>: <msg>"`.
- Add a UT next to UT-045: a callback that raises for term A marks A `failed` and leaves B untouched.

## Triage

- Decision: `VALID`
- Notes: Root cause: callback exceptions bypass errbacks, and spider_error handling was optional.
- Fix applied (spec-only round, no code exists): _spec.md rule 28 and registry comments; ADR-002 Implementation Notes make spider_error mandatory; US-005.EC-6; UT-049.
- Verified (round 2): rule 28, ADR-002 Implementation Notes make the `spider_error` handler mandatory with `response.meta["term"]` attribution, US-005.EC-6, UT-049 asserts the message, kept jobs, no further request and an untouched term B.
