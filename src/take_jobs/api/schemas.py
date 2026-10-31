"""Response models of the HTTP API (`_dx.md` > HTTP API). Extra keys are rejected so the same
models can validate a document produced elsewhere, such as the CLI's `--json`."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict

from take_jobs.domain.models import ResultStatus, RunStatus, RunTrigger, Seniority


class _Out(BaseModel):
    model_config = ConfigDict(extra="forbid", from_attributes=True)


class JobOut(_Out):
    id: int
    title: str
    company: str | None
    location: str | None
    description: str | None
    published_label: str | None
    source: str
    url: str
    seniority: Seniority | None
    first_seen_at: datetime
    last_seen_at: datetime
    active: bool


class JobPageOut(_Out):
    items: list[JobOut]
    total: int
    page: int
    size: int
    pages: int


class TotalsOut(_Out):
    new: int
    seen_again: int
    discarded: int


class CombinationResultOut(_Out):
    source: str
    term: str
    status: ResultStatus
    pages: int
    new: int
    seen_again: int
    discarded: int
    error: str | None


class RunSummaryOut(_Out):
    id: int
    trigger: RunTrigger
    status: RunStatus
    started_at: datetime
    finished_at: datetime | None
    error: str | None
    totals: TotalsOut


class RunDetailOut(RunSummaryOut):
    results: list[CombinationResultOut]


class RunPageOut(_Out):
    items: list[RunSummaryOut]
    total: int
    page: int
    size: int
    pages: int


class HealthOut(_Out):
    status: Literal["ok", "unavailable"]
    database: Literal["ok", "unreachable"]


class ErrorDetailOut(_Out):
    field: str
    message: str


class ErrorBodyOut(_Out):
    code: str
    message: str
    details: list[ErrorDetailOut]


class ErrorOut(_Out):
    error: ErrorBodyOut
