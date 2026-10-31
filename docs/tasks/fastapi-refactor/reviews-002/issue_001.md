---
provider: manual
pr:
round: 2
round_created_at: 2026-10-30T20:39:57Z
status: resolved
file: docs/tasks/fastapi-refactor/_spec.md
line: 244
severity: high
author: claude-code
provider_ref:
---

# Issue 001: Report pipe read after child exit deadlocks every real-size crawl

## Review Comment

**Problem.** The revision moved the crawl into a `spawn` child (review round 1, issue 001). `_spec.md` › System Architecture, data flow step 3 (line 244), prescribes this hand-off: the child "sends the `ScrapeReport` … back through a pipe. The parent blocks until the child exits, then returns the report…". ADR-002 Decision 2 says the same. This is the ordering the `multiprocessing` docs warn against ("joining processes that use pipes/queues"). `Connection.send` blocks once the OS socket buffer is full. A parent that waits for the child to exit before reading never drains the pipe, so neither process can make progress.

**Runtime evidence.** A spawn child sends a `ScrapeReport` built from the spec's dataclasses. The parent calls `join(timeout=15)` and then `recv()`:

```
Linux (python:3.13-slim, the production/CI platform)
jobs=    72 pickled_report=    10.2 KiB  join-then-recv: ok
jobs=   300 pickled_report=    38.5 KiB  join-then-recv: ok
jobs=  1778 pickled_report=   234.0 KiB  join-then-recv: DEADLOCK (child still alive after 15 s, blocked in send)
jobs= 14400 pickled_report=  1902.8 KiB  join-then-recv: DEADLOCK
macOS (Python 3.13.4): DEADLOCK at every size, including 72 jobs / 10.2 KiB
```

1,778 jobs is the Golden Path run (`_dx.md`: new=1184, seen_again=203, discarded=391). The worst case is about 14k cards (12 terms × 20 pages × 40 vagas cards plus 12 × 20 × 20 Infojobs cards).

**Why the tests will not catch it.** IT-007, IT-013 and E2E-001 to E2E-004 use fixture pages of 20–40 cards, about 100 jobs or 15 KiB, which pass on Linux CI. The first full production run hangs. On the author's macOS machine the same tests hang instead.

**Impact.** All of the following hold once the hang occurs:
- The crawl finishes, but the child never exits and the collector blocks forever. Nothing is ingested.
- The run stays `running`. That breaks Safety Invariant 9 and rule 13's claim that takeover "can only hit a dead process". After 60 min the next start marks it `interrupted`, while the hung process lives on.
- The scheduler's runner waits on that collector. With `max_instances=1`, every later 06:00 run is skipped as "maximum number of running instances reached". The daily collection stops silently until a restart.
- A crash has a related failure mode. If the parent keeps its copy of the child's pipe end open, `recv()` never gets EOF, so `ScrapeCrashedError` ("exited without a report") can never be raised.

**Suggested fix.**
- Specify the hand-off order in `_spec.md` step 3 and ADR-002:
  - the parent closes its copy of the child's end right after `start()`;
  - it waits with `multiprocessing.connection.wait([conn, process.sentinel])` and reads the report **before** `join()`;
  - EOF or a sentinel without a report means `ScrapeCrashedError` with the exit code.
- Alternatively, have the child write the report to a temp file (pickle) and send only the path.
- Add a test that a report of at least 1 MiB crosses the real child boundary within a bound. For example, a UT next to UT-108: the child target is replaced by a top-level function that sends 15,000 synthetic `ScrapedJob`s, and `scrape()` returns within 30 s. Because IT-007's fixture sizes stay under the Linux buffer, this case needs its own test.

## Triage

- Decision: `VALID`
- Notes: Root cause: the spec told the parent to join the child before reading the pipe, so the child blocks in send() once the report exceeds the OS pipe buffer.
- Fix applied (spec-only round, no code exists): _spec.md data flow step 3: one-way pipe; the parent closes the child's end after start(), waits on connection.wait([conn, sentinel]), and recv()s before join(); EOF or the sentinel without a report means ScrapeCrashedError. Safety Invariant 5 and ADR-002 Decision 2 updated. Tests: UT-109 (15,000 jobs, >1 MiB, returns within 30 s on Linux and macOS), UT-108 now bounded by a 10 s timeout.
- Verified (round 3, 2026-10-30): the hand-off in data flow step 3, Invariant 5 and ADR-002 was implemented as specified (spawn, `Pipe(duplex=False)`, parent closes the child end after `start()`, `connection.wait([conn, sentinel])`, `recv()` before `join()`). On macOS / Python 3.13.4, a 15,000-job report (1,356 KiB pickled) returned in 0.7 s, and a child that exits 1 without a report returned at once with exit code 1. UT-108 (10 s bound) and UT-109 (>1 MiB, 30 s) pin both.
