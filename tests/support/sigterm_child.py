"""A short-lived stand-in for the collector, for UT-089.

It handles SIGTERM like the real collector under a stop: it takes a second to wind down, then exits
with code 4. `READY_FILE` (an environment variable) is created once the handler is installed, so
the test never signals a child that would still die by the default action. A self-timeout keeps a
broken test from leaving the process behind.
"""

import os
import signal
import sys
import time
from pathlib import Path

WIND_DOWN_S = 1.0
SELF_TIMEOUT_S = 20.0
EXIT_INTERRUPTED = 4


def _on_sigterm(signum: int, frame: object) -> None:
    time.sleep(WIND_DOWN_S)
    sys.exit(EXIT_INTERRUPTED)


def main() -> int:
    signal.signal(signal.SIGTERM, _on_sigterm)
    Path(os.environ["READY_FILE"]).write_text("ready")
    deadline = time.monotonic() + SELF_TIMEOUT_S
    while time.monotonic() < deadline:
        time.sleep(0.05)
    return 5


if __name__ == "__main__":
    sys.exit(main())
