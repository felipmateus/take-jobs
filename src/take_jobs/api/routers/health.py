"""`GET /health`: pings the database, giving up after three seconds."""

import asyncio
import logging
from typing import Annotated

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse

from take_jobs.api.dependencies import get_job_store_probe
from take_jobs.api.schemas import HealthOut
from take_jobs.domain.ports import JobStoreProbe

PROBE_TIMEOUT_SECONDS = 3.0

logger = logging.getLogger("take_jobs.api")

router = APIRouter(tags=["health"])


@router.get(
    "/health",
    response_model=HealthOut,
    summary="Liveness and database reachability",
    responses={503: {"model": HealthOut, "description": "The database is unreachable."}},
)
async def health(probe: Annotated[JobStoreProbe, Depends(get_job_store_probe)]):
    try:
        async with asyncio.timeout(PROBE_TIMEOUT_SECONDS):
            await probe.ping()
    except Exception as exc:
        logger.warning("event=api_health_failed error=%s: %s", type(exc).__name__, exc)
        return JSONResponse(
            status_code=503,
            content=HealthOut(status="unavailable", database="unreachable").model_dump(),
        )
    return HealthOut(status="ok", database="ok")
