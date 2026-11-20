"""Publishing readiness diagnostics (read-only, no secrets)."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Query

from app.api.deps import CurrentUserDep, SessionDep, SettingsDep
from app.schemas.publishing_readiness import PublishingReadinessResponse
from app.services.publishing_readiness import PublishingReadinessService

router = APIRouter(prefix="/publishing", tags=["publishing"])

OptionalCanaryPostId = Annotated[
    UUID | None,
    Query(
        description="Optional scheduled post ID to check against the live canary allowlist.",
    ),
]


@router.get("/readiness", response_model=PublishingReadinessResponse)
async def get_publishing_readiness(
    user: CurrentUserDep,
    session: SessionDep,
    settings: SettingsDep,
    post_id: OptionalCanaryPostId = None,
) -> PublishingReadinessResponse:
    return await PublishingReadinessService(session, settings=settings).diagnose(
        user, post_id=post_id
    )
