"""What `take-jobs collect` prints: the human summary lines and the `--json` document.

The JSON document has the shape of `GET /collection-runs/{id}` (`_dx.md`). It is built here
because the `cli` package must not import `take_jobs.api`.
"""

import json
from datetime import UTC, datetime, timedelta
from typing import Any

from take_jobs.domain.models import (
    CollectionRun,
    CombinationResult,
    ResultStatus,
    RunStatus,
    RunTrigger,
)


def _iso(moment: datetime) -> str:
    """UTC ISO-8601 with a `Z` suffix, like the API's timestamps."""
    return moment.astimezone(UTC).isoformat().replace("+00:00", "Z")


def started_line(run_id: int, trigger: RunTrigger) -> str:
    return f"Collection run {run_id} started (trigger: {trigger.value})"


def already_active_message(run_id: int, started_at: datetime) -> str:
    stamp = started_at.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    return f"Another collection run (id {run_id}) is in progress since {stamp}."


def _duration(delta: timedelta) -> str:
    seconds = max(0, int(delta.total_seconds()))
    hours, rest = divmod(seconds, 3600)
    minutes, seconds = divmod(rest, 60)
    if hours:
        return f"{hours}h{minutes:02d}m{seconds:02d}s"
    if minutes:
        return f"{minutes}m{seconds:02d}s"
    return f"{seconds}s"


def _result_line(result: CombinationResult, source_width: int, term_width: int) -> str:
    ok = result.status is ResultStatus.SUCCESS
    line = (
        f"{result.source:<{source_width}}{result.term:<{term_width}}"
        f"{'ok' if ok else 'FAILED':<8}"
        f"{f'pages={result.pages}':<10}"
        f"{f'new={result.new}':<9}"
        f"{f'seen_again={result.seen_again}':<16}"
    )
    discarded = f"discarded={result.discarded}"
    if result.error is None:
        return line + discarded
    return f"{line}{discarded:<15}error={json.dumps(result.error, ensure_ascii=False)}"


def summary_lines(run: CollectionRun) -> list[str]:
    """One line per source x term, then the `finished` line."""
    source_width = max((len(r.source) for r in run.results), default=0) + 2
    term_width = max((len(r.term) for r in run.results), default=0) + 2
    lines = [_result_line(result, source_width, term_width) for result in run.results]
    elapsed = timedelta(0) if run.finished_at is None else run.finished_at - run.started_at
    lines.append(
        f"Collection run {run.id} finished: {run.status.value} in {_duration(elapsed)} "
        f"(new={run.totals.new}, seen_again={run.totals.seen_again}, "
        f"discarded={run.totals.discarded})"
    )
    return lines


def run_as_json(run: CollectionRun) -> str:
    """The run as one JSON document (the `GET /collection-runs/{id}` shape)."""
    document: dict[str, Any] = {
        "id": run.id,
        "trigger": run.trigger.value,
        "status": run.status.value,
        "started_at": _iso(run.started_at),
        "finished_at": None if run.finished_at is None else _iso(run.finished_at),
        "error": run.error,
        "totals": {
            "new": run.totals.new,
            "seen_again": run.totals.seen_again,
            "discarded": run.totals.discarded,
        },
        "results": [
            {
                "source": result.source,
                "term": result.term,
                "status": result.status.value,
                "pages": result.pages,
                "new": result.new,
                "seen_again": result.seen_again,
                "discarded": result.discarded,
                "error": result.error,
            }
            for result in run.results
        ],
    }
    return json.dumps(document, ensure_ascii=False)


def exit_code_for(status: RunStatus) -> int:
    """`success` and `partial` exit 0; a `failed` run exits 1."""
    return 0 if status in (RunStatus.SUCCESS, RunStatus.PARTIAL) else 1
