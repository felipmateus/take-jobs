---
schema_version: "spec-tasks/v2"
workflow: fastapi-refactor
graph:
  nodes:
    - id: task_01
      file: task_01.md
    - id: task_02
      file: task_02.md
    - id: task_03
      file: task_03.md
    - id: task_04
      file: task_04.md
    - id: task_05
      file: task_05.md
    - id: task_06
      file: task_06.md
    - id: task_07
      file: task_07.md
    - id: task_08
      file: task_08.md
    - id: task_09
      file: task_09.md
    - id: task_10
      file: task_10.md
  edges:
    - from: task_01
      to: task_02
    - from: task_02
      to: task_03
    - from: task_02
      to: task_04
    - from: task_02
      to: task_05
    - from: task_03
      to: task_05
    - from: task_04
      to: task_06
    - from: task_05
      to: task_06
    - from: task_06
      to: task_07
    - from: task_06
      to: task_08
    - from: task_07
      to: task_09
    - from: task_08
      to: task_09
    - from: task_09
      to: task_10
---

# Tasks: take-jobs v2 — FastAPI refactor

Task graph for [`_spec.md`](_spec.md). Test IDs come from [`_tests.md`](_tests.md); each one is owned by exactly one task.

**Slice 1 (Motivating Problem).** Tasks 01 to 07 deliver it end to end: `take-jobs collect` stores jobs scraped from the sites, and `GET /jobs` returns them, searchable and paginated (E2E-001).

One deviation from the spec's slice note: both sources (vagas.com and Infojobs) ship in task 04. Most spider and parser test cases cover both sources, so splitting them would split test ownership. The spec treats slices as an ordering, not a scope cut, so nothing is deferred.

| Task | Title | Type | Complexity | Depends on | Owns tests |
| --- | --- | --- | --- | --- | --- |
| task_01 | Foundation: tooling, package skeleton and settings | chore | low | — | UT-020–UT-027, UT-115, UT-118 |
| task_02 | Domain model, ports and business rules | feature | medium | task_01 | UT-001–UT-019 |
| task_03 | Persistence: PostgreSQL schema, repositories and unit of work | backend | high | task_02 | IT-001–IT-006, IT-010 |
| task_04 | Scraping: parsers, spiders and the spawned crawl child | backend | critical | task_02 | UT-030–UT-049, UT-106–UT-109, UT-116, UT-119 |
| task_05 | Application services: search, run history and collection | backend | high | task_02, task_03 | UT-050–UT-068, IT-008 |
| task_06 | CLI `take-jobs collect` with signal-safe run lifecycle | feature | critical | task_04, task_05 | UT-070–UT-079, UT-104, UT-105, UT-117, IT-007, IT-009, IT-013 |
| task_07 | HTTP API: search, detail, run history, health and docs | feature | medium | task_06 | UT-090–UT-103, IT-011, E2E-001–E2E-005 |
| task_08 | Scheduler: daily cron, startup catch-up and signal forwarding | feature | high | task_06 | UT-080–UT-089 |
| task_09 | Packaging: Dockerfile, Docker Compose and `.env.example` | infra | medium | task_07, task_08 | UT-110, IT-012, MAN-001, MAN-003 |
| task_10 | Delivery evidence: CI, README v1 → v2, `v1` tag and O5 query | docs | low | task_09 | UT-111–UT-114, IT-014, MAN-002, MAN-004, MAN-005 |

**Environment requirement.** Every `IT-*` and `E2E-*` case needs Docker, for testcontainers PostgreSQL 17. A task whose integration gate cannot run because Docker is unavailable must stop and report the gap rather than mark itself `completed`.
