"""A root logger with no handlers, as a fresh process (uvicorn, `take-jobs`) has it."""

import contextlib
import logging
from collections.abc import Iterator


@contextlib.contextmanager
def bare_root_logger() -> Iterator[logging.Logger]:
    """Empty the root logger (pytest's capture handlers included), then restore it."""
    root = logging.getLogger()
    handlers, level = root.handlers[:], root.level
    root.handlers.clear()
    try:
        yield root
    finally:
        for handler in root.handlers:
            handler.close()
        root.handlers[:] = handlers
        root.setLevel(level)
