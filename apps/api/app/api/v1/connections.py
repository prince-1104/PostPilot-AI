"""LinkedIn connection status and disconnect."""

from fastapi import APIRouter

from app.api.deps import CurrentUserDep, RequireOriginDep, SessionDep
from app.schemas.auth import LinkedInConnectionResponse
from app.services.connections import ConnectionService

router = APIRouter(prefix="/connections", tags=["connections"])


@router.get("/linkedin", response_model=LinkedInConnectionResponse)
async def get_linkedin_connection(
    user: CurrentUserDep,
    session: SessionDep,
) -> LinkedInConnectionResponse:
    return await ConnectionService(session).get_linkedin_status(user)


@router.post("/linkedin/disconnect", response_model=LinkedInConnectionResponse)
async def disconnect_linkedin(
    user: CurrentUserDep,
    session: SessionDep,
    _: RequireOriginDep,
) -> LinkedInConnectionResponse:
    return await ConnectionService(session).disconnect_linkedin(user)
