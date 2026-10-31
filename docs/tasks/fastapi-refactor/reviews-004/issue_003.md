---
provider: manual
pr:
round: 4
round_created_at: 2026-10-30T22:26:40Z
status: resolved
file: docs/tasks/fastapi-refactor/_tests.md
line: 364
severity: low
author: claude-code
provider_ref:
---

# Issue 003: UT-116 expects a class name the recorded error never contains

## Review Comment

**Problem.** UT-116 was rewritten in round 3 for `reviews-001/issue_010`. It expects "every outcome has an `error` containing `SocketConnectBlockedError`" (`_tests.md` line 364). The error-format contract for request failures records only the exception **message**:
- `_spec.md` Integration Points (line 747): "A final failure fails the combination with `HTTP <code> <reason>` or the exception message."
- ADR-002 Implementation Notes (line 104): "timeouts → the exception message".

The message of pytest-socket's `SocketConnectBlockedError` does not contain the class name.

Runtime evidence, using Python 3.13.4, Scrapy 2.19.0, Twisted 26.10.0 and pytest-socket 0.8.1 (scratch script `guard_errback.py`). The setup is a spawn child with the specified guard, `socket_allow_hosts` plus a `connect_ex` wrapper and `allow_hosts=("::1",)`, sending a Scrapy request to a 127.0.0.1 server. The errback receives:
- `type(failure.value)`: `pytest_socket.SocketConnectBlockedError`;
- `str(failure.value)` and `failure.getErrorMessage()`: `A test tried to use socket.socket.connect() with host "127.0.0.1" (allowed: "::1").`;
- server hits: 0.

The guard works. An implementation that follows the error contract, however, records a string without `SocketConnectBlockedError`, so UT-116 fails. The implementer must then either change the error format or weaken the test, and neither choice is specified.

**Suggested fix.** Choose one:
- Change UT-116 to assert that the error contains the guard's message, for example `A test tried to use socket.socket.connect()`, together with the 0-hit assertion.
- Specify the generic errback format as `<ExceptionType>: <message>`, like rule 28's `parse error: <ExceptionType>: <message>`, and update `_spec.md` Integration Points and ADR-002 to match.

## Triage

- Decision: `VALID`
- Notes: Root cause: the generic errback format recorded only the exception message, while UT-116 expected the class name.
- Fix applied (spec-only round, no code exists): _spec.md Integration Points and ADR-002 errbacks now record `<ExceptionType>: <message>` for non-HTTP, non-robots failures (timeouts included); UT-116 expects an error starting with `SocketConnectBlockedError: `.
- Verified: (review round 5) `_spec.md` Integration Points (vagas row) now reads `HTTP <code> <reason>`, `blocked by robots.txt`, or otherwise `<ExceptionType>: <message>` (e.g. `TimeoutError: ...`); ADR-002 Implementation Notes line 105 specifies `type(failure.value).__name__`; UT-116 (`_tests.md` line 379) expects an error starting with `SocketConnectBlockedError: `. Round 4's runtime evidence showed `type(failure.value)` is `pytest_socket.SocketConnectBlockedError` in the errback, so a contract-following implementation now satisfies UT-116. No other artifact still describes the old message-only format (grep over `_spec.md`, `_tests.md`, `_dx.md`, `_user_stories.md`, `adrs/`).
