"""`GET /jobs` and `GET /jobs/{job_id}`."""

from collections.abc import Sequence
from datetime import date
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, Query
from pydantic import StringConstraints

from take_jobs.api.dependencies import get_job_query_service
from take_jobs.api.errors import responses
from take_jobs.api.params import PageParam, SizeParam
from take_jobs.api.schemas import JobOut, JobPageOut
from take_jobs.application.services import JobQuery, JobQueryService
from take_jobs.domain.models import Seniority

SearchText = Annotated[str, StringConstraints(strip_whitespace=True, max_length=100)]


def build_router(source_ids: Sequence[str]) -> APIRouter:
    """The `source` parameter is an enum of the registered source ids, so the API never names a
    site (US-007): a new registry entry is accepted and documented without touching this module."""
    source_type: Any = Literal[tuple(source_ids)]  # type: ignore[valid-type]
    router = APIRouter(tags=["jobs"])

    @router.get(
        "/jobs",
        response_model=JobPageOut,
        summary="Search jobs",
        responses=responses(422, 503),
    )
    async def search_jobs(
        service: Annotated[JobQueryService, Depends(get_job_query_service)],
        q: Annotated[SearchText | None, Query(description="Title, company or description.")] = None,
        source: Annotated[list[source_type] | None, Query()] = None,
        location: Annotated[SearchText | None, Query(description="Contains.")] = None,
        seniority: Annotated[list[Seniority] | None, Query()] = None,
        seen_from: Annotated[date | None, Query(description="Last seen on or after.")] = None,
        seen_to: Annotated[date | None, Query(description="First seen on or before.")] = None,
        include_inactive: bool = False,
        page: PageParam = 1,
        size: SizeParam = 20,
    ) -> JobPageOut:
        found = await service.search(
            JobQuery(
                q=q or None,
                sources=frozenset(source or ()),
                location=location or None,
                seniorities=frozenset(seniority or ()),
                seen_from=seen_from,
                seen_to=seen_to,
                include_inactive=include_inactive,
                page=page,
                size=size,
            )
        )
        return JobPageOut(
            items=[JobOut.model_validate(job) for job in found.items],
            total=found.total,
            page=found.page,
            size=found.size,
            pages=found.pages,
        )

    @router.get(
        "/jobs/{job_id}",
        response_model=JobOut,
        summary="Get one job",
        responses=responses(404, 422, 503),
    )
    async def get_job(
        job_id: int,
        service: Annotated[JobQueryService, Depends(get_job_query_service)],
    ) -> JobOut:
        return JobOut.model_validate(await service.get(job_id))

    return router
