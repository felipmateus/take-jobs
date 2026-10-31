"""Pure business rules (stdlib only): normalization, relevance, seniority, run status,
startup reason and standard-cron day-of-week handling. Spec: Business Rules 4-15."""

import unicodedata
from collections.abc import Sequence
from datetime import datetime, timedelta
from typing import Literal

from take_jobs.domain.models import CombinationResult, ResultStatus, RunStatus, Seniority

STARTUP_RECENT_RUN_WINDOW = timedelta(hours=24)

# Rule 7. Keywords are written already normalized.
_SENIORITY_KEYWORDS: dict[Seniority, tuple[str, ...]] = {
    Seniority.INTERN: ("estagio", "estagiario", "estagiaria", "intern", "internship"),
    Seniority.JUNIOR: ("junior", "jr", "trainee"),
    Seniority.MID: ("pleno", "mid", "mid level"),
    Seniority.SENIOR: (
        "senior",
        "sr",
        "especialista",
        "specialist",
        "lead",
        "lider",
        "tech lead",
        "principal",
        "staff",
    ),
}


def normalize(text: str) -> str:
    """Rule 4: lowercase, accents removed, non-alphanumerics become spaces, spaces collapsed."""
    decomposed = unicodedata.normalize("NFKD", text.lower())
    stripped = "".join(char for char in decomposed if not unicodedata.combining(char))
    spaced = "".join(char if char.isalnum() else " " for char in stripped)
    return " ".join(spaced.split())


def _padded(normalized: str) -> str:
    """Surround with spaces so a whole word or phrase is a plain substring test."""
    return f" {normalized} "


class RelevancePolicy:
    """Rules 5 and 6: relevant = at least one include keyword and no exclude keyword."""

    def __init__(self, include: Sequence[str], exclude: Sequence[str]) -> None:
        self._include = self._normalize_keywords(include)
        if not self._include:
            raise ValueError("include keywords must not be empty")
        self._exclude = self._normalize_keywords(exclude)

    @staticmethod
    def _normalize_keywords(keywords: Sequence[str]) -> tuple[str, ...]:
        return tuple(dict.fromkeys(key for key in map(normalize, keywords) if key))

    def is_relevant(self, title: str) -> bool:
        padded = _padded(normalize(title))
        if any(_padded(keyword) in padded for keyword in self._exclude):
            return False
        return any(_padded(keyword) in padded for keyword in self._include)


def classify_seniority(title: str) -> Seniority | None:
    """Rules 7 and 8: the keyword starting left-most in the normalized title wins."""
    padded = _padded(normalize(title))
    best: tuple[int, int, Seniority] | None = None  # (start, -length, level)
    for level, keywords in _SENIORITY_KEYWORDS.items():
        for keyword in keywords:
            start = padded.find(_padded(keyword))
            if start == -1:
                continue
            candidate = (start, -len(keyword), level)
            if best is None or candidate[:2] < best[:2]:
                best = candidate
    return best[2] if best else None


def final_run_status(results: Sequence[CombinationResult]) -> RunStatus:
    """Rule 12. No result at all is not a success, so it is `failed`."""
    successes = sum(1 for result in results if result.status is ResultStatus.SUCCESS)
    if successes == 0:
        return RunStatus.FAILED
    if successes == len(results):
        return RunStatus.SUCCESS
    return RunStatus.PARTIAL


def startup_collection_reason(
    store_empty: bool, latest_finished_started_at: datetime | None, now: datetime
) -> Literal["empty_job_store", "no_recent_run"] | None:
    """Rule 14. Empty store first. Otherwise no finished run, or the latest started more than
    24 h before now (exactly 24 h still counts as recent)."""
    if store_empty:
        return "empty_job_store"
    if latest_finished_started_at is None:
        return "no_recent_run"
    if now - latest_finished_started_at > STARTUP_RECENT_RUN_WINDOW:
        return "no_recent_run"
    return None


# Standard cron day-of-week: 0 and 7 are Sunday. Index = standard number (0-6).
_DAY_NAMES = ("sun", "mon", "tue", "wed", "thu", "fri", "sat")


def _dow_number(value: str) -> int:
    lowered = value.lower()
    if lowered in _DAY_NAMES:
        return _DAY_NAMES.index(lowered)
    if value.isascii() and value.isdigit():
        number = int(value)
        if 0 <= number <= 7:
            return number
    raise ValueError(f"invalid day-of-week value {value!r}")


def _expand_dow_item(item: str) -> set[int]:
    base, slash, step_text = item.partition("/")
    if slash:
        if not (step_text.isascii() and step_text.isdigit()) or int(step_text) < 1:
            raise ValueError(f"invalid day-of-week step {step_text!r}")
        step = int(step_text)
    else:
        step = 1
    if base == "*":
        first, last = 0, 6
    elif "-" in base:
        low, high = base.split("-", 1)
        first, last = _dow_number(low), _dow_number(high)
        if first > last:
            raise ValueError(f"invalid day-of-week range {base!r}")
    else:
        first = _dow_number(base)
        last = 7 if slash else first
    return {number % 7 for number in range(first, last + 1, step)}


def to_standard_crontab(expr: str) -> str:
    """Make the day-of-week field follow standard cron under APScheduler's `from_crontab`
    (whose numbering and name ranges are Monday-first).

    The field is parsed as standard cron: numbers 0-7 with 0 and 7 = Sunday, names sun-sat,
    ranges, lists and steps. It is re-emitted as an explicit comma list of names in Sunday-first
    order (for example "0-4" becomes "sun,mon,tue,wed,thu"), so no emitted range can wrap.
    "*" stays "*". Raises ValueError for an invalid field. Other fields are unchanged.
    """
    fields = expr.split()
    if len(fields) != 5:
        raise ValueError(f"expected 5 cron fields, got {len(fields)}")
    dow = fields[4]
    if dow == "*":
        return " ".join(fields)
    days: set[int] = set()
    for item in dow.split(","):
        if not item:
            raise ValueError(f"invalid day-of-week field {dow!r}")
        days |= _expand_dow_item(item)
    fields[4] = ",".join(_DAY_NAMES[day] for day in sorted(days))
    return " ".join(fields)
