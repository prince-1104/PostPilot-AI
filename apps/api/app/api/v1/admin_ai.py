"""Admin-only AI observability endpoints."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query

from app.api.deps import CurrentUserDep, SessionDep, SettingsDep
from app.core.errors import ForbiddenError
from app.models import User
from app.schemas.ai_analytics import AiAnalyticsSummary, ThreadInspectionResponse
from app.services.ai_analytics import AiAnalyticsService, resolve_window, user_is_admin

router = APIRouter(prefix="/admin/ai", tags=["admin-ai"])


async def require_admin(
    user: CurrentUserDep,
    settings: SettingsDep,
) -> User:
    if not user_is_admin(
        user,
        admin_user_ids=settings.admin_user_ids,
        admin_emails=settings.admin_emails,
    ):
        raise ForbiddenError("Administrator access required.")
    return user


AdminUserDep = Annotated[User, Depends(require_admin)]


@router.get("/analytics", response_model=AiAnalyticsSummary)
async def get_ai_analytics(
    _admin: AdminUserDep,
    session: SessionDep,
    preset: Annotated[str | None, Query(pattern="^(24h|7d|30d)$")] = "7d",
    from_time: datetime | None = None,
    to_time: datetime | None = None,
) -> AiAnalyticsSummary:
    start, end = resolve_window(preset=preset, from_time=from_time, to_time=to_time)
    return await AiAnalyticsService(session).summary(from_time=start, to_time=end)


@router.get("/threads/{thread_id}", response_model=ThreadInspectionResponse)
async def inspect_ai_thread(
    thread_id: UUID,
    _admin: AdminUserDep,
    session: SessionDep,
) -> ThreadInspectionResponse:
    return await AiAnalyticsService(session).inspect_thread(thread_id=thread_id)
