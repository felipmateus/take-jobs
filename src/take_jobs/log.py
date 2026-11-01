"""Process logging: `level=<LEVEL> key=value ...` lines, shared by the CLI and the API."""

import logging

LOG_FORMAT = "level=%(levelname)s %(message)s"


def configure_logging(level: str) -> None:
    """Send the root logger to stderr in `LOG_FORMAT` at `level` (`LOG_LEVEL`).

    `logging.basicConfig` semantics: a root logger that already has handlers is left alone, so
    a test runner's capture keeps its own setup. Uvicorn's loggers do not propagate to the root,
    so its access lines keep their own format and are not printed twice.
    """
    logging.basicConfig(level=level, format=LOG_FORMAT)
