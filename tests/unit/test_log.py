"""`configure_logging`: the `level=<LEVEL> key=value` lines shared by the CLI and the API."""

import logging

import pytest

from take_jobs.log import LOG_FORMAT, configure_logging
from tests.support.logs import bare_root_logger


def test_writes_key_value_lines_to_stderr(capsys: pytest.CaptureFixture[str]) -> None:
    with bare_root_logger() as root:
        configure_logging("INFO")
        logging.getLogger("take_jobs.api").warning("event=api_health_failed error=X: y")

        assert root.level == logging.INFO
        assert [h.formatter._fmt for h in root.handlers if h.formatter] == [LOG_FORMAT]

    assert capsys.readouterr().err == "level=WARNING event=api_health_failed error=X: y\n"


def test_level_filters_lower_records(capsys: pytest.CaptureFixture[str]) -> None:
    with bare_root_logger():
        configure_logging("WARNING")
        logging.getLogger("take_jobs.api").info("event=hidden")
        logging.getLogger("take_jobs.api").error("event=shown")

    assert capsys.readouterr().err == "level=ERROR event=shown\n"


def test_leaves_a_configured_root_logger_alone() -> None:
    with bare_root_logger() as root:
        existing = logging.NullHandler()
        root.addHandler(existing)
        root.setLevel(logging.ERROR)

        configure_logging("DEBUG")

        assert root.handlers == [existing]
        assert root.level == logging.ERROR
