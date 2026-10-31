---
provider: manual
pr:
round: 1
round_created_at: 2026-10-30T20:10:01Z
status: resolved
file: docs/tasks/fastapi-refactor/_tests.md
line: 313
severity: high
author: claude-code
provider_ref:
---

# Issue 001: E2E/IT crawls in one pytest process hit ReactorNotRestartable

## Review Comment

**Problem.** `_tests.md` › End-to-End Tests says every E2E case drives `take_jobs.cli.main.main([...])` in-process with the real composition, and the fixture server. The real `collect` path runs `asyncio.run` → `CrawlerProcess.start()` → `asyncio.run` (`_spec.md` › System Architecture, data flow steps 2–4; ADR-002). ADR-002 line 19 itself says a Twisted reactor cannot be restarted within a process. But the suite starts many crawls in one pytest session:
- IT-007 (one crawl).
- E2E-001, E2E-002 (two `collect` calls: "A second `collect`"), E2E-003 (two calls) and E2E-004.

Only the first crawl in the session can work. The E2Es also mix `httpx.AsyncClient` (async tests on the session loop, `_tests.md` › Strategy) with `main()`, which calls `asyncio.run`. That raises when it is called from a running loop.

**Runtime evidence** (Scrapy 2.19.0, Python 3.13, `TWISTED_REACTOR=None` as the spec prescribes, spider with no requests, so no network):
```
collect #1: ok
collect #2: twisted.internet.error.ReactorNotRestartable:
asyncio.run inside running loop: asyncio.run() cannot be called from a running event loop
```
Script: two `asyncio.run → CrawlerProcess.start → asyncio.run` cycles in one process, then `asyncio.run` from inside a coroutine.

**Missing seams the tests assume but no artifact defines:**
- How `main(argv)` receives fakes. UT-070–UT-078 use a "fake service and scraper".
- How the "real composition" in the E2Es points the registry and `base_url` at the fixture server. No config key exists for it, and IT-012 requires the `.env.example` keys to equal the `Settings` fields exactly.
- The `create_app` signature that UT-102 needs to inject a registry with `fakeboard`, while uvicorn calls `create_app` with no arguments (`--factory`).

**Suggested fix.**
1. Pick one crawl-isolation strategy and write it into ADR-002 and `_tests.md`. Option A: E2Es run `collect` as a subprocess (`python -m take_jobs collect`), with the fixture server URL passed through a documented test-only seam. Option B: `ScrapyJobScraper` runs the crawl in a `multiprocessing` spawn child (ADR-002's rejected Alternative 3), so the CLI can be called many times in one process.
2. State that E2E tests calling `main()` are sync tests, or that they call `main()` through `asyncio.to_thread`.
3. Specify the composition seams: e.g. `main(argv, *, deps: CollectDeps | None = None)` and `create_app(settings: Settings | None = None, sources: Mapping[str, SourceDefinition] | None = None)`.

## Triage

- Decision: `VALID`
- Notes: Root cause: the crawl ran in the collector process; the Twisted reactor cannot restart, and no DI seams were specified. User decision (2026-10-30): crawl in a multiprocessing spawn child.
- Fix applied (spec-only round, no code exists): ADR-002 Decision and revision note; _spec.md data flow step 3, Core Interfaces (CliDeps, build_cli_deps, main(argv, deps=), create_app(settings=, sources=), SourceDefinition.base_url, with_base_url), Safety Invariant 5, Known Risks R1/R6; _tests.md Strategy (sync E2E with TestClient), IT-007 runs two collects, E2E preamble.
- Verified (round 2, 2026-10-30): the crawl runs in a `spawn` child (ADR-002 Decision; `_spec.md` data flow step 3, Safety Invariant 5, R1/R6). `CliDeps`, `build_cli_deps`, `main(argv, deps=)`, `create_app(settings=, sources=)` and `with_base_url` are specified. E2E tests are synchronous with `TestClient`, and IT-007 runs two collects in one process. `python -m take_jobs` is safe under spawn, because multiprocessing skips re-running a `*.__main__` module. The report-pipe ordering that this design introduced deadlocks; it is tracked separately as reviews-002/issue_001, so it is not reopened here.
