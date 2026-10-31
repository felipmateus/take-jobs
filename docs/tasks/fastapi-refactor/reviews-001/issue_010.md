---
provider: manual
pr:
round: 1
round_created_at: 2026-10-30T20:10:01Z
status: resolved
file: docs/tasks/fastapi-refactor/_tests.md
line: 112
severity: medium
author: claude-code
provider_ref:
---

# Issue 010: O1 (100% FRs with an automated test) unreachable: 6 FRs manual-only

## Review Comment

**Problem.** PRD O1 requires every FR to be covered by at least one task **and at least one automated test**, with a target of 100%. In the coverage matrix (`_tests.md` lines 112–118), these FRs have only manual checks or no test at all:
- FR-27, one-command startup: MAN-001.
- FR-29, CI on push and PR: MAN-004.
- FR-31, README sections: MAN-005.
- FR-32, `v1` tag → `52018b3`: MAN-005.
- FR-33, artifacts versioned: MAN-005.
- FR-30, no dependence on the real sites: "enforced by every IT/E2E using the fixture server". That is a convention, and no test asserts it.

So O1 tops out at about 82%, and the portfolio's headline traceability claim fails.

**Suggested fix.** Add cheap static tests. None needs the network.
- FR-27: parse `docker-compose.yml` and assert the services `db`, `migrate`, `api` and `scheduler`, with the ordering conditions.
- FR-29: parse `.github/workflows/ci.yml` and assert `on: [push, pull_request]` and the steps for format, lint, `lint-imports` and `pytest --cov-fail-under=80`.
- FR-31: assert the README's required headings, including "v1 → v2".
- FR-32: `git rev-parse v1^{commit}` == `52018b3…`, skipped when tags are absent in a shallow CI clone (or fetch tags in CI).
- FR-33: assert that the artifact files exist.
- FR-30: a session-wide socket guard that allows only localhost and the testcontainers host (e.g. `pytest-socket` with `--allow-hosts`).

Keep MAN-001/004/005 for the live parts.

## Triage

- Decision: `VALID`
- Notes: Root cause: FR-27 and FR-29-FR-33 had only manual owners, so O1 was unreachable.
- Fix applied (spec-only round, no code exists): _spec.md Testing Approach (static contract tests, pytest-socket guard, fetch-depth 0); _tests.md UT-110-UT-115 and matrix rows.
- Reopened (round 2, 2026-10-30): the static contract tests UT-110 to UT-114 close the O1 gap for FR-27 and FR-29 to FR-33. The FR-30 bullet of this issue is still open, because the guard does not cover the only code that makes outbound HTTP requests:
  - Every scraping request runs in the spawned crawl child. `_tests.md` Strategy itself says "Spawned children inherit no guard, so they only ever receive fixture-server URLs", which is a convention again. Runtime: under `pytest --disable-socket --allow-unix-socket --allow-hosts=127.0.0.1,::1,localhost` (pytest-socket, Python 3.13), a `spawn` child's `connect()` to a non-local address was attempted on the network (it ended in `TimeoutError`, not a pytest-socket error).
  - The child's follow-up URLs are not fully controlled by `with_base_url`. v1 built the vagas.com next page as the hard-coded `https://www.vagas.com.br` + `#maisVagas@data-url` (`git show 52018b3:src/sync_app/bots/takeJobs/takeJobs/spiders/vagas.py`, lines 28–32). The spec's own field mapping uses the same hard-coded-origin pattern for job URLs. No test pins that `next_url` is resolved against `page_url`, because UT-031 uses the real origin as `page_url`. A parser written that way makes IT-007, E2E-001 and IT-013 fetch pages 2+ and `robots.txt` from the real vagas.com.br, and nothing fails.
  - UT-115 cannot pass as written. With `--allow-hosts`, pytest-socket raises `pytest_socket.SocketConnectBlockedError` (MRO: `SocketConnectBlockedError → RuntimeError`), not `SocketBlockedError`. The test as specified fails.
  Fix:
  - Enforce FR-30 inside the child. For example, spiders derive `allowed_domains` from `base_url` (Scrapy's `OffsiteMiddleware` then drops off-host requests), or the scraper takes a test-only allowed-hosts guard that it installs in the child.
  - Add a UT where `vagas.parse_listing(p1, "http://127.0.0.1:9999/vagas-de-python")` returns a `next_url` on `127.0.0.1:9999`.
  - Correct UT-115's exception class.
- Round-2 fix: URL resolution rule in _spec.md Integration Points (urljoin against page_url for job url and next_url, allowed_domains from base_url, off-origin follow-ups fail the term with 'parse error: OffOriginURLError'); field-mapping url cells updated. Test seam ScrapyJobScraper/build_cli_deps(child_initializer=install_test_socket_guard) installs the network guard in the crawl child; the spec's Testing Approach and _tests.md Strategy are updated. UT-115 now expects SocketConnectBlockedError. New UT-039 (off-origin guard) and UT-116 (guard in child); UT-031 adds a 127.0.0.1 page_url case.
- Reopened (round 3, 2026-10-30): UT-031, UT-039, the URL-resolution rule, `allowed_domains` and the UT-115 class are correct. The crawl-child network guard, which this fix makes the enforcement of FR-30 "in the process that makes the requests" (`_spec.md` › Testing Approach, `_tests.md` Strategy, matrix row US-021.AC-2), does not stop Scrapy:
  - pytest-socket 0.8.1 `socket_allow_hosts` (the `--allow-hosts` mode) patches only `socket.socket.connect`. Twisted's TCP client connects with `socket.connect_ex` (`twisted/internet/tcp.py:626`), which is never guarded.
  - Runtime (scratch script `guard_bypass.py`, Python 3.13.4, Scrapy 2.19.0, Twisted 26.10.0): in a spawn child, `child_initializer` installs `socket_allow_hosts(["::1"], allow_unix_socket=True)`, and a local server listens on 127.0.0.1 (not allowed). Then:
    - `socket.create_connection(("127.0.0.1", port))` raises `SocketConnectBlockedError`. This is the path UT-116 tests, so UT-116 passes.
    - A Scrapy request to `http://127.0.0.1:<port>/vagas-de-python` in the same child gets `HTTP 200`, and the server records 1 hit.
    With the guard's real allow-list, a crawl that reaches vagas.com.br, for example through a parser regression past the off-origin check or a redirect, is not blocked, and UT-116 stays green. UT-116 is hollow for the code it claims to cover.
  - Control (scratch script `guard_with_connect_ex.py`): when `connect_ex` is also wrapped with the same guard, the Scrapy request fails in its errback with `SocketConnectBlockedError`, and the server gets 0 hits.
  Fix:
  - Specify `install_test_socket_guard` as pytest-socket's guard **plus** a `socket.socket.connect_ex` wrapper. Or use a Scrapy-level guard, for example a test downloader middleware or `allowed_domains` alone, and stop claiming socket-level enforcement in the child.
  - Rewrite UT-116 so that the child makes a **Scrapy** request to a host that is not allowed, and asserts that the request fails with the guard's error while the server records 0 hits.
- Round-3 fix: install_test_socket_guard is specified as pytest-socket socket_allow_hosts PLUS a socket.socket.connect_ex wrapper with the same allow-list (Twisted connects with connect_ex), with an optional allow_hosts bound via functools.partial. UT-116 rewritten: a real Scrapy crawl in the child to a 127.0.0.1 server not on the allow list fails with SocketConnectBlockedError and the server gets 0 hits; a control case with the default guard reaches the server. Files: _spec.md Testing Approach, _tests.md UT-116.
- Verified (round 4, 2026-10-30): `_spec.md` Testing Approach now specifies `install_test_socket_guard` as pytest-socket `socket_allow_hosts` plus a `socket.socket.connect_ex` wrapper with the same allow-list, and UT-116 uses a real Scrapy crawl in the spawned child. Runtime (scratch `guard_errback.py`, Python 3.13.4, Scrapy 2.19.0, Twisted 26.10.0, pytest-socket 0.8.1): with `allow_hosts=("::1",)` the request to a 127.0.0.1 server reaches the spider's errback as `pytest_socket.SocketConnectBlockedError` (raised from `twisted/internet/tcp.py:626` `connect_ex`) and the server records 0 hits, robots.txt included; the control case with loopback allowed records 2 hits (`/robots.txt`, `/vagas-de-python`) and a 200. FR-30 is enforced in the crawl child. One assertion detail of the rewritten UT-116 (it expects the class name in the recorded error, which the errback contract does not record) is tracked as `reviews-004/issue_003.md`.
