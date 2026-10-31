---
provider: manual
pr:
round: 4
round_created_at: 2026-10-30T22:26:40Z
status: resolved
file: docs/tasks/fastapi-refactor/_spec.md
line: 611
severity: low
author: claude-code
provider_ref:
---

# Issue 002: Stop during the startup run always waits the full 25 s

## Review Comment

**Problem.** Round 3 changed two things:
- The scheduler installs `make_shutdown_handler` before `run_startup` (`_spec.md` Scheduler start-up, `run_scheduler`).
- `SubprocessCollectionRunner` blocks in `run()` until the collector exits (`_spec.md` line 609; UT-084, "sets `current` while waiting").

`run_startup` runs in the **main** thread, so during the startup collection the main thread is inside `Popen.wait()`. With no timeout, CPython's `Popen._wait` blocks in `os.waitpid(pid, 0)` while it **holds** `Popen._waitpid_lock`. When SIGTERM arrives:
1. `waitpid` gets `EINTR`, and the Python handler runs in that same thread while the lock is still held.
2. The handler calls `terminate_current(25)`, and UT-084 prescribes `current.terminate()` then `current.wait(timeout=25)`.
3. The timed wait only polls with `_waitpid_lock.acquire(False)`. That never succeeds, because the lock's owner is the suspended frame below the handler.

So the handler always waits the full `wait_s`, then calls `kill()` on what is by then a zombie, even when the collector exited within its ~10 s budget.

Runtime evidence, Python 3.13.4 (scratch script `startup_wait_lock.py`):
- The runner does `Popen(...).wait()` in the main thread, and the handler is `terminate_current(wait_s=8)`.
- The child handles SIGTERM, sleeps 2 s, then exits `4`.
- SIGTERM arrives 1 s into the run. Output:

```
wait TIMED OUT after 8.0s -> kill()
handler done 8.0s after SIGTERM
```

With the specified `wait_s=25`, every `docker compose down` or Ctrl+C during the startup collection takes 25 s and ends in a spurious `kill()`. That leaves less than 5 s of the 30 s `stop_grace_period` (Safety Invariant 8) for the interpreter and tini to exit.

The wait does return as soon as the collector exits in the scheduled path, where the job runs in an APScheduler worker thread. So the same handler behaves differently on the two paths, and UT-087 and UT-088 cannot see the difference: they use a fake runner, and UT-084 patches `Popen`.

**Suggested fix.**
- In `SubprocessCollectionRunner.run()`, wait without holding the lock across a blocking call. For example, loop `while proc.poll() is None: time.sleep(0.2)` (`poll()` only try-acquires the lock), or run `run_startup`'s collection in a worker thread.
- In `terminate_current`, poll the same way instead of calling `wait(timeout=…)`.
- Add a UT with a real short-lived child, no `Popen` patch. Run `run()` in the main thread and invoke the installed handler from a timer, using `os.kill(os.getpid(), SIGTERM)`. The child exits 1 s after its SIGTERM, and the expected result is that the handler returns within about 2 s, without `kill()`.

## Triage

- Decision: `VALID`
- Notes: Root cause: SubprocessCollectionRunner.run() blocked in Popen.wait() in the main thread, holding _waitpid_lock while the signal handler's wait(timeout) needed it.
- Fix applied (spec-only round, no code exists): _spec.md SubprocessCollectionRunner: run() polls proc.poll() every 0.2 s and never calls a blocking wait(); terminate_current polls the same way, then SIGKILLs after wait_s. Tests: UT-084 asserts that wait() is never called; new UT-089 uses a real child in the main thread, and the handler returns within 3 s without kill().
- Verified: (review round 5) `_spec.md` lines 617-629 specify `run()` as `while proc.poll() is None: time.sleep(0.2)` and `terminate_current` as poll-then-SIGKILL, never `Popen.wait()`; UT-084 asserts `wait()` is never called and the new UT-089 uses a real child in the main thread. Runtime: a scratch script implementing exactly that runner and handler (`run()` in the main thread, `os.kill(getpid(), SIGTERM)` from a timer 1 s in, child sleeps 1 s on SIGTERM then exits 4) printed `SystemExit(0) 1.22s after SIGTERM; killed=False; child code=4` on Python 3.13.4 and `1.02s` on 3.11.5, versus the 8.0 s timeout + `kill()` reproduced in round 4.
