"""Composition root for the process commands (`take-jobs`).

`take-jobs collect` is implemented in `take_jobs.cli.collect`, `take-jobs scheduler` in
`take_jobs.cli.scheduler`. `CliDeps` and `build_cli_deps`
live in `take_jobs.cli.deps` and are re-exported here, as `_spec.md` names them.
"""

import argparse
import sys
from collections.abc import Sequence

from pydantic import ValidationError

from take_jobs.cli.collect import run_collect
from take_jobs.cli.deps import CliDeps, build_cli_deps
from take_jobs.cli.scheduler import run_scheduler
from take_jobs.config import Settings
from take_jobs.domain.models import RunTrigger
from take_jobs.log import configure_logging

__all__ = ["CliDeps", "build_cli_deps", "main"]

EXIT_INVALID_CONFIGURATION = 2


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="take-jobs",
        description="Coleta diária de vagas de emprego (vagas.com e Infojobs).",
    )
    commands = parser.add_subparsers(dest="command", required=True, metavar="{collect,scheduler}")
    collect = commands.add_parser(
        "collect",
        help="run one collection now, for every registered source and configured term",
        description=(
            "Run one collection now. Exit codes: 0 success or partial, 1 failed, "
            "2 invalid configuration, 3 another run in progress, 4 stopped by SIGTERM/SIGINT."
        ),
    )
    collect.add_argument(
        "--trigger",
        choices=[trigger.value for trigger in RunTrigger],
        default=RunTrigger.MANUAL.value,
        help="trigger recorded on the run (default: manual)",
    )
    collect.add_argument(
        "--json",
        dest="json_output",
        action="store_true",
        help="print only the final run as JSON, in the GET /collection-runs/{id} shape",
    )
    commands.add_parser(
        "scheduler",
        help="run the daily collection scheduler (SCRAPE_CRON in SCRAPE_TIMEZONE)",
        description=(
            "Wait for the database, collect on start when the store is empty or no run finished "
            "in the last 24 hours (SCRAPE_ON_START), then collect daily on SCRAPE_CRON. "
            "SIGTERM/SIGINT is forwarded to a running collector. Exit codes: 0 stopped by a "
            "signal, 1 database unavailable, 2 invalid configuration."
        ),
    )
    return parser


def _configuration_lines(error: ValidationError) -> list[str]:
    """`Invalid configuration: <KEY>: <reason>`, one line per invalid key."""
    lines = []
    for item in error.errors():
        key = ".".join(str(part) for part in item["loc"])
        reason = item["msg"].removeprefix("Value error, ")
        lines.append(f"Invalid configuration: {key}: {reason}")
    return lines


def _load_deps() -> CliDeps | None:
    try:
        settings = Settings()
    except ValidationError as error:
        for line in _configuration_lines(error):
            print(line, file=sys.stderr)
        return None
    configure_logging(settings.log_level)
    return build_cli_deps(settings)


def main(argv: Sequence[str] | None = None, *, deps: CliDeps | None = None) -> int:
    parser = _build_parser()
    try:
        args = parser.parse_args(sys.argv[1:] if argv is None else list(argv))
    except SystemExit as exit_request:  # argparse: --help (0) or a usage error (2)
        code = exit_request.code
        return code if isinstance(code, int) else 0
    if deps is None:
        deps = _load_deps()
        if deps is None:
            return EXIT_INVALID_CONFIGURATION
    if args.command == "scheduler":
        return run_scheduler(deps)
    return run_collect(deps, RunTrigger(args.trigger), json_output=args.json_output)
