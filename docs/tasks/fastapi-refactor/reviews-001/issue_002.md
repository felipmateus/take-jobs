---
provider: manual
pr:
round: 1
round_created_at: 2026-10-30T20:10:01Z
status: resolved
file: docs/tasks/fastapi-refactor/_spec.md
line: 221
severity: high
author: claude-code
provider_ref:
---

# Issue 002: Ingest failure unhandled; one bad row loses the run, stays running

## Review Comment

**Problem.** The data flow defines a failure path only for the crawl: "If step 3 raises, `fail_run` runs instead" (`_spec.md` line 221; ADR-002 Decision 3). Nothing specifies what happens when step 4, `complete_run`, raises. Safety Invariant 3 (line 717) puts every upsert of the run in **one transaction**. So any single row-level database error rolls back the whole day's ingestion. The run then stays `running` with no error. A day later, the next start marks it `failed` with the misleading error `interrupted`, and the same deterministic failure can repeat every day. `_dx.md` › CLI exit codes do not cover this case either.

Row-level errors that are realistic with scraped input:
- `published_label varchar(64)`, `external_id varchar(64)` and `source varchar(32)` overflow (`_spec.md` lines 466, 471). A selector that drifts after a site HTML change easily returns more than 64 characters.
- NUL characters (`\x00`), which PostgreSQL `text` rejects.

**Runtime evidence** (postgres:16, the spec's DDL): in one transaction, one valid insert followed by an insert with a 65-character `published_label` gives
```
ERROR:  value too long for type character varying(64)
select count(*) from jobs where external_id='2'  -> 0   (the valid row is lost too)
```

**Suggested fix.**
- Add a contract for ingest failure:
  - the CLI catches exceptions from `complete_run`;
  - it calls `fail_run(run_id, "ingest failed: <ExceptionType>: <msg>")` in a fresh transaction;
  - it exits `1` (add this case to the `_dx.md` exit-code table).
- Make scraped input safe before the database sees it:
  - parsers truncate `published_label`, or drop the length limit and use `text`;
  - parsers reject or skip cards whose `external_id` is longer than 64 characters;
  - parsers strip `\x00`.
- Add a unit test for the parser or `ScrapedJob` construction, and an IT where `complete_run` meets a database error: the run ends `failed` with the error recorded, and the exit code is `1`.

## Triage

- Decision: `VALID`
- Notes: Root cause: no failure contract for complete_run, plus bounded varchar columns fed by scraped text.
- Fix applied (spec-only round, no code exists): _spec.md rules 26-27, data flow step 5, Safety Invariant 3, published_label -> text; _dx.md exit table and Errors; US-003.EC-6; UT-038, UT-079, IT-008 rewritten.
- Verified (round 2): rules 26–27, data flow step 5 table, Safety Invariant 3 with fresh-transaction `fail_run`; `published_label` is `text`; ids > 64 chars skipped and NUL stripped (UT-038); UT-079 and IT-008 assert `ingest failed: …` and exit `1`; `_dx.md` exit table and Errors updated.
