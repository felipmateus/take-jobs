"""`SubprocessCollectionRunner` (UT-084 with `Popen` patched, UT-089 with a real child).

UT-089 delivers a real SIGTERM to the test process, in the main thread, so it is a sync test and it
restores the original handlers.
"""

import logging
import os
import signal
import stat
import sys
import threading
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any, ClassVar

import pytest

from take_jobs.cli import runner as runner_module
from take_jobs.cli.runner import SubprocessCollectionRunner
from take_jobs.cli.scheduler import make_shutdown_handler
from take_jobs.domain.models import RunTrigger

CHILD = Path(__file__).parents[2] / "support" / "sigterm_child.py"


class FakePopen:
    """Records its arguments; `poll()` returns `exit_after` consecutive `None`s, then `code`.

    `wait` fails the test: the runner must poll (review round 4, issue 002).
    """

    instances: ClassVar[list["FakePopen"]] = []

    def __init__(self, argv: list[str], **kwargs: Any) -> None:
        self.argv = argv
        self.kwargs = kwargs
        self.polls = 0
        self.exit_after = 3
        self.code = 7
        self.returncode: int | None = None
        self.terminated = False
        self.killed = False
        FakePopen.instances.append(self)

    def poll(self) -> int | None:
        self.polls += 1
        if self.killed or self.polls > self.exit_after:
            self.returncode = -9 if self.killed else self.code
        return self.returncode

    def wait(self, timeout: float | None = None) -> int:
        raise AssertionError("the runner must never call Popen.wait()")

    def terminate(self) -> None:
        self.terminated = True

    def kill(self) -> None:
        self.killed = True


class FakeTime:
    """A virtual clock: `sleep` advances `monotonic` without waiting."""

    def __init__(self) -> None:
        self.now = 1000.0
        self.sleeps: list[float] = []

    def monotonic(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds


@pytest.fixture
def fake_popen(monkeypatch: pytest.MonkeyPatch) -> type[FakePopen]:
    FakePopen.instances = []
    monkeypatch.setattr(runner_module.subprocess, "Popen", FakePopen)
    return FakePopen


@pytest.fixture
def fake_time(monkeypatch: pytest.MonkeyPatch) -> FakeTime:
    clock = FakeTime()
    monkeypatch.setattr(runner_module, "time", clock)
    return clock


def test_run_builds_the_argv_polls_and_returns_the_exit_code(
    fake_popen: type[FakePopen], fake_time: FakeTime, caplog: pytest.LogCaptureFixture
) -> None:
    runner = SubprocessCollectionRunner()
    seen_current: list[object] = []
    original_sleep = fake_time.sleep

    def sleep_and_observe(seconds: float) -> None:
        seen_current.append(runner.current)
        original_sleep(seconds)

    fake_time.sleep = sleep_and_observe  # type: ignore[method-assign]

    with caplog.at_level(logging.INFO, logger="take_jobs.cli.runner"):
        code = runner.run(RunTrigger.SCHEDULED)

    (child,) = fake_popen.instances
    assert child.argv == [sys.executable, "-m", "take_jobs", "collect", "--trigger", "scheduled"]
    assert child.kwargs == {"shell": False}
    assert code == 7
    assert seen_current == [child, child, child]  # current is set while waiting
    assert runner.current is None  # and cleared afterwards
    assert fake_time.sleeps == [0.2, 0.2, 0.2]
    assert "event=collector_exited trigger=scheduled exit_code=7" in caplog.text


def test_run_clears_current_when_waiting_is_interrupted(
    fake_popen: type[FakePopen], fake_time: FakeTime
) -> None:
    runner = SubprocessCollectionRunner()

    def interrupted(seconds: float) -> None:
        raise SystemExit(0)

    fake_time.sleep = interrupted  # type: ignore[method-assign]
    with pytest.raises(SystemExit):
        runner.run(RunTrigger.STARTUP)
    assert runner.current is None


def test_terminate_current_sends_sigterm_and_polls_until_the_child_exits(
    fake_popen: type[FakePopen], fake_time: FakeTime
) -> None:
    runner = SubprocessCollectionRunner()
    child = FakePopen([], shell=False)
    child.exit_after = 4
    runner.current = child  # type: ignore[assignment]

    runner.terminate_current(25)

    assert child.terminated
    assert not child.killed
    assert child.polls == 5
    assert fake_time.sleeps == [0.2] * 4


def test_terminate_current_kills_when_the_wait_runs_out(
    fake_popen: type[FakePopen], fake_time: FakeTime
) -> None:
    runner = SubprocessCollectionRunner()
    child = FakePopen([], shell=False)
    child.exit_after = 10**9  # never exits by itself
    runner.current = child  # type: ignore[assignment]

    runner.terminate_current(25)

    assert child.terminated
    assert child.killed
    assert 25 <= sum(fake_time.sleeps) < 25.5


def test_terminate_current_does_not_kill_just_before_the_deadline(
    fake_popen: type[FakePopen], fake_time: FakeTime
) -> None:
    runner = SubprocessCollectionRunner()
    child = FakePopen([], shell=False)
    child.exit_after = 120  # exits at about 24 s of polling
    runner.current = child  # type: ignore[assignment]

    runner.terminate_current(25)

    assert not child.killed


def test_terminate_current_is_a_no_op_when_idle(
    fake_popen: type[FakePopen], fake_time: FakeTime
) -> None:
    SubprocessCollectionRunner().terminate_current(25)

    assert fake_popen.instances == []
    assert fake_time.sleeps == []


class StubScheduler:
    running = False

    def shutdown(self, wait: bool = True) -> None:
        raise AssertionError("the scheduler is not running")


@pytest.fixture
def restored_signal_handlers() -> Iterator[None]:
    before = {sig: signal.getsignal(sig) for sig in (signal.SIGTERM, signal.SIGINT)}
    yield
    for sig, handler in before.items():
        signal.signal(sig, handler)
    assert {sig: signal.getsignal(sig) for sig in before} == before


def test_a_stop_during_the_startup_run_returns_once_the_collector_exits(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, restored_signal_handlers: None
) -> None:
    """UT-089: real runner, real child, real SIGTERM, main thread, no `Popen` patch."""
    ready = tmp_path / "ready"
    launcher = tmp_path / "python"
    launcher.write_text(f'#!/bin/sh\nexec "{sys.executable}" "{CHILD}"\n')
    launcher.chmod(launcher.stat().st_mode | stat.S_IXUSR)
    monkeypatch.setenv("READY_FILE", str(ready))
    # The runner builds its argv from `sys.executable`; the launcher swaps the collector for the
    # SIGTERM child while keeping the real `Popen`, the real polling and the real signal.
    monkeypatch.setattr(sys, "executable", str(launcher))

    runner = SubprocessCollectionRunner()
    signal.signal(signal.SIGTERM, make_shutdown_handler(StubScheduler(), runner, wait_s=25))  # type: ignore[arg-type]
    observed: dict[str, Any] = {}

    def send_stop() -> None:
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline and not ready.exists():
            time.sleep(0.02)
        child = runner.current
        observed["child"] = child
        if child is None or not ready.exists():  # the test fails on the missing `child`
            return
        real_kill = child.kill
        child.kill = lambda: (observed.setdefault("killed", True), real_kill())  # type: ignore[method-assign]
        observed["sent_at"] = time.monotonic()
        os.kill(os.getpid(), signal.SIGTERM)

    timer = threading.Thread(target=send_stop, daemon=True)
    timer.start()
    try:
        with pytest.raises(SystemExit) as stop:
            runner.run(RunTrigger.STARTUP)
        elapsed = time.monotonic() - observed["sent_at"]
    finally:
        timer.join(timeout=5)
        child = observed.get("child")
        if child is not None and child.poll() is None:  # never leave the child behind
            child.kill()
            child.poll()

    assert stop.value.code == 0
    assert elapsed < 3
    assert "killed" not in observed
    assert observed["child"].returncode == 4
    assert runner.current is None
