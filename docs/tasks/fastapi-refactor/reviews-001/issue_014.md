---
provider: manual
pr:
round: 1
round_created_at: 2026-10-30T20:10:01Z
status: resolved
file: docs/tasks/fastapi-refactor/_tests.md
line: 309
severity: medium
author: claude-code
provider_ref:
---

# Issue 014: IT-012 secret check is undefined; v1 password stays exposed via tag

## Review Comment

**Problem 1: the test cannot be written as specified.** IT-012's last bullet ("No file tracked by git contains a password other than `take_jobs_dev`") gives no detection rule. A test cannot recognise "a password" in arbitrary files. The implementer has to invent patterns, and the result will be either hollow or noisy.

**Problem 2: the v1 credential stays exposed.** v1 committed a real-looking MySQL root password. It is visible in `git show 52018b3:src/sync_app/app.py` (line 22, inside `SQLALCHEMY_DATABASE_URI`) and in `src/sync_app/bots/takeJobs/takeJobs/pipelines.py` (line 28). This finding deliberately does not quote it. Deleting the files in v2 does not remove it from history. FR-32 creates a `v1` tag on that exact commit, and the README "v1 → v2" section (`_spec.md` lines 735–739) points readers to those very files.

The PRD security constraint ("v1 committed a database password, which must not happen again") is met only for new commits. No artifact says:
- that the leaked value must be treated as compromised (rotated wherever it was reused);
- that it must never be quoted in the README, the docs or the review files (which are versioned under FR-33).

**Suggested fix.**
- Make IT-012 mechanical. For example:
  - scan `git ls-files` for `(?i)(password|passwd|secret)\s*[:=]\s*\S+` and for URLs with an inline password (`://[^:/\s]+:[^@\s]+@`);
  - allow only the documented dev default in `docker-compose.yml`, `.env.example` and `_dx.md`;
  - or adopt a scanner such as `gitleaks` in CI with an allowlist.
- Add to the spec or README contract:
  - the v1 password is considered leaked and must be rotated if it is used anywhere;
  - the "v1 → v2" section cites the file paths only, never the value.

## Triage

- Decision: `VALID`
- Notes: Root cause: the IT-012 secret check had no detection rule, and the leaked v1 password had no handling policy. User confirmed (2026-10-30) the v1 password is no longer used anywhere.
- Fix applied (spec-only round, no code exists): IT-012 mechanical regex scan with allowlist that never prints values; _spec.md User Experience > Credentials, Impact Analysis tag row, File References: never quote the value, cite paths only. Tag v1 unchanged.
- Reopened (round 2, 2026-10-30): the never-quote policy holds. A script extracted the v1 value from `52018b3:src/sync_app/app.py` without printing it and found it in no working-tree file, including `docs/`. The IT-012 secret scan, though, still cannot be written as specified, because it fails on the repository's own versioned artifacts. Running the two IT-012 patterns, with the stated allowlist, over `docs/tasks/fastapi-refactor/**/*.md` (all versioned under FR-33, and therefore in `git ls-files`) gives:
  - `_tests.md:418`: the URL pattern matches its own documentation and captures a regex fragment.
  - `reviews-001/issue_014.md:28`: the same.
  The test module that implements the scan will hold the same regex literal, and will match too. Under "any other captured value fails the test", IT-012 fails deterministically, so the implementer has to invent exclusions.
  Fix: specify the exclusions, for example skip `docs/tasks/**` and the scan's own test module, or only flag values that look like credentials (a length or entropy floor, no regex metacharacters). Then add a self-check case: the scan passes on the current tree and fails on a synthetic fixture holding `postgresql://u:hunter2@h/db`.
- Round-2 fix: the IT-012 secret-scan scope excludes docs/**/*.md (the never-quote policy still applies and is checked at review) and the scan's own module and fixtures. Self-check cases added: it passes on the tree, fails on leak.env (reported as file:line, value never printed), and passes on ok.env.
- Verified (round 3, 2026-10-30): IT-012 now names its exclusions (`docs/**/*.md`, the scan module and `tests/fixtures/secrets/`) and has pass/fail self-check fixtures. The two IT-012 patterns with that scope and allowlist were run over `git ls-files` plus untracked files: 0 hits. A script extracted the v1 value from `52018b3:src/sync_app/app.py` without printing it; no working-tree file contains it.
