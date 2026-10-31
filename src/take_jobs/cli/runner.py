"""Starts the collector as a subprocess (scheduler side, ADR-004, Safety Invariant 6).

The command is built from `sys.executable` and the trigger's enum value, never through a shell.
The runner keeps the `Popen` handle so the scheduler can forward SIGTERM, and it waits by polling:
a blocking `Popen.wait()` in the main thread holds `Popen`'s waitpid lock while the signal handler
runs, so the handler's own wait could never succeed (review round 4, issue 002).
"""

import logging
import subprocess
import sys
import time
from typing import Protocol

from take_jobs.domain.models import RunTrigger

logger = logging.getLogger(__name__)

_POLL_INTERVAL_S = 0.2


class CollectionRunner(Protocol):
    def run(self, trigger: RunTrigger) -> int:
        """Start the collector, block until it exits, return its exit code."""

    def terminate_current(self, wait_s: float) -> None:
        """SIGTERM to the running collector, if any; poll for up to `wait_s`, then SIGKILL.
        A no-op when idle."""


class SubprocessCollectionRunner:
    """Implements `CollectionRunner` with `python -m take_jobs collect --trigger <trigger>`."""

    def __init__(self) -> None:
        self.current: subprocess.Popen[bytes] | None = None

    def run(self, trigger: RunTrigger) -> int:
        process = subprocess.Popen(
            [sys.executable, "-m", "take_jobs", "collect", "--trigger", trigger.value],
            shell=False,
        )
        self.current = process
        try:
            while process.poll() is None:
                time.sleep(_POLL_INTERVAL_S)
            code = process.returncode
        finally:
            self.current = None
        logger.info("event=collector_exited trigger=%s exit_code=%s", trigger.value, code)
        return code

    def terminate_current(self, wait_s: float) -> None:
        process = self.current
        if process is None:
            return
        process.terminate()
        deadline = time.monotonic() + wait_s
        while process.poll() is None:
            if time.monotonic() >= deadline:
                process.kill()
                return
            time.sleep(_POLL_INTERVAL_S)
