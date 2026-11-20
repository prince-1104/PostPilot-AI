"""Liveness and readiness endpoints."""

from fastapi import APIRouter

from app.api.deps import SessionDep, SettingsDep
from app.schemas.errors import ErrorResponse
from app.schemas.health import LivenessResponse, ReadinessChecks, ReadinessResponse
from app.services.health import check_database

router = APIRouter(prefix="/health", tags=["health"])


@router.get(
    "/live",
    response_model=LivenessResponse,
    summary="Liveness probe",
    description="Confirms the process is serving requests. Does not touch external services.",
)
async def live() -> LivenessResponse:
    return LivenessResponse()


@router.get(
    "/ready",
    response_model=ReadinessResponse,
    summary="Readiness probe",
    description="Confirms the API can serve traffic by querying PostgreSQL.",
    responses={503: {"model": ErrorResponse, "description": "PostgreSQL is not reachable."}},
)
async def ready(session: SessionDep, settings: SettingsDep) -> ReadinessResponse:
    await check_database(session, timeout_seconds=settings.readiness_timeout_seconds)
    return ReadinessResponse(checks=ReadinessChecks(database="ok"))
