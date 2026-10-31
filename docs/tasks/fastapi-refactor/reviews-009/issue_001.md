---
provider: manual
pr:
round: 9
round_created_at: 2026-10-31T01:34:43Z
status: valid
file: docs/tasks/fastapi-refactor/_tasks.md
line: 63
severity: low
author: claude-code
provider_ref:
---

# Issue 001: UT-118 and UT-119 are not owned by any task in _tasks.md

## Review Comment

The round-8 fix added two new test IDs to `_tests.md`: UT-118 (Config, `SCRAPE_TERMS` slug rules) and UT-119 (Scraper child, the `finished` close reason). It did not assign either ID to a task. This breaks the task graph's contract at `_tasks.md:55`: "Test IDs come from `_tests.md`; each one is owned by exactly one task."

Evidence:
- `_tasks.md:63` (task_01, "Owns tests") lists `UT-020–UT-027, UT-115`. `_tasks.md:66` (task_04) lists `UT-030–UT-049, UT-106–UT-109, UT-116`. Neither lists UT-118 or UT-119. The `## Tests` checklists in `task_01.md` (line 75) and `task_04.md` (line 81) do not list them either.
- I ran a script that expands every "Owns tests" range in `_tasks.md` and compares the result with the `- **UT-/IT-NNN**` definitions in `_tests.md`. It found 130 IDs defined, and the only IDs not owned by a task are `['UT-118', 'UT-119']`.
- Earlier rounds set the convention. The IDs added during review (UT-115, UT-116 and UT-117) were each added to the owning row in `_tasks.md` and to the `## Tests` checklist in that task file.

Impact: traceability only. The tests exist and pass (`-k "ut118 or ut119"`). But the cy-review-round test-contract parity check works from task ownership, so a later change could drop these tests without any task's verification noticing. That is the failure mode reviews-008 issue 001 was opened to close. This is non-blocking.

Suggested fix: add UT-118 to the task_01 row and UT-119 to the task_04 row in `_tasks.md`. Add matching `- [x] UT-118 — ...` and `- [x] UT-119 — ...` lines to the `## Tests` sections of `task_01.md` and `task_04.md`, plus their "Verify in this task" lines. Do this the same way UT-115 and UT-116 were added. This is a docs-only change.

## Triage

- Decision: `VALID`
- Notes:
  - Confirmed locally. `_tests.md` defines UT-118 (line 210) and UT-119 (line 378), and before this fix neither ID appeared in any "Owns tests" cell of `_tasks.md` or in a task `## Tests` checklist. The tests are real, and the spec and `_tests.md` coverage tables already reference them.
  - Root cause: the round-7 fix added the two IDs to `_tests.md` without assigning an owner. This is a traceability gap only, so no source or test change is needed.
  - Fix, docs only, the same way UT-115, UT-116 and UT-117 were added:
    - `_tasks.md`: UT-118 appended to the task_01 row, UT-119 appended to the task_04 row.
    - `task_01.md`: UT-118 added to "Verify in this task", to Deliverables and to the `## Tests` checklist (`- [x] UT-118 ...`). UT-118 is owned by task_01 because it exercises `Settings` (config).
    - `task_04.md`: UT-119 added to "Verify in this task" and to the `## Tests` checklist (`- [x] UT-119 ...`). UT-119 is owned by task_04 because it exercises the scraper child close-reason mapping.
    - Task frontmatter is unchanged (`status: completed` in both).
  - Verification: a script expanded every "Owns tests" range in `_tasks.md` and compared it with the `- **ID**` definitions in `_tests.md`. Result: 140 IDs defined (116 UT, 14 IT, 5 E2E, 5 MAN), 140 owned, 0 unowned, 0 owned but undefined, 0 owned by more than one task. The reviewer's count of 130 covered UT and IT only.
  - No pytest gate was run, since no source or test file changed.
