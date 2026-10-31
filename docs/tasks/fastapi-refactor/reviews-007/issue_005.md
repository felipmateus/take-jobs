---
provider: manual
pr:
round: 7
round_created_at: 2026-10-31T00:56:07Z
status: resolved
file: tests/conftest.py
line: 112
severity: low
author: claude-code
provider_ref:
---

# Issue 005: Container start retry swallows any error silently, up to 10 min

## Review Comment

`_start_postgres` (task_07) retries `PostgresContainer.start()` 5 times on **any** `Exception` (`tests/conftest.py:108-118`). It does re-raise after the fifth attempt, so a *persistent* failure still surfaces. It is weaker than its purpose (the cold-Docker Ryuk port-mapping race) in three ways:

1. **Too broad, and slow to fail.** `start()` includes the PostgreSQL readiness wait, whose default timeout in testcontainers 4.15 is `TC_MAX_TRIES × TC_POOLING_INTERVAL` = 120 s. A real start-up failure (bad image or configuration, a container that never becomes ready, a failed pull) is retried 5 times, about 5 × 122 s ≈ 10 minutes, before the suite errors.
2. **Hides intermittent real failures, and keeps no record.** An attempt that fails and is then retried successfully leaves no trace: no warning and no log line. Flaky Docker problems therefore become invisible in CI.
3. **Loses the root cause.** Only the last attempt's exception is raised. When the first failure differs from later ones (for example the Ryuk race, then a name conflict), the original cause is discarded.

The retry path itself was never exercised after the fix (`memory/task_07.md`: "not forced again"). `Reaper.delete_instance()` does stop the half-created reaper in the observed case: the `ConnectionError` is raised by `get_exposed_port(8080)` after `Reaper._container` is set, so the logic is sound for that race.

Suggested fix:
- Retry only the known race: `ConnectionError` whose message starts with `Port mapping`, or more broadly a failure raised while `Reaper._instance is None`. Re-raise anything else immediately.
- Emit `warnings.warn(...)`, or a terminal-reporter line, for each swallowed attempt.
- Chain the first exception into the final one (`raise last from first`).
- Optionally add a unit test that monkeypatches `PostgresContainer.start` to fail once with the race error and then succeed, and to fail with another error that must propagate on the first attempt.

## Triage

- Decision: `VALID`
- Notes:
  - Valid on all three points: `_start_postgres` retried on any `Exception` (up to about 10 minutes for a real start-up failure), left no trace of swallowed attempts, and raised only the last exception.
  - Fix in `tests/conftest.py`: retry only `ConnectionError` whose message starts with `Port mapping` (the observed Ryuk race); any other exception is raised on the first attempt; each swallowed attempt emits a `RuntimeWarning` naming the attempt and the error; if all five attempts hit the race, the last error is raised `from` the first. Cleanup (`container.stop()`, `Reaper.delete_instance()`) is unchanged.
  - Tests: new `tests/unit/test_container_start_retry.py` with a fake container (no Docker): race then success (warning, cleanup), other error propagates at once, a `ConnectionError` that is not the race propagates at once, five races raise the fifth chained to the first, a different error after a race propagates.
- Verified (round 8): `_start_postgres` retries only a `ConnectionError` whose message starts with `Port mapping`. testcontainers 4.15 raises exactly that at `core/docker_client.py:372`. Any other error is raised on the first attempt, each swallowed attempt emits a `RuntimeWarning`, and the final race is raised `from` the first. No `filterwarnings = error` is configured, so the warning cannot itself abort the session. `tests/unit/test_container_start_retry.py` (5 cases, fake container, no Docker) passed.
