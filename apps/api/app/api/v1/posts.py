"""Scheduled post HTTP routes."""

from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Header, Query

from app.api.deps import CurrentUserDep, RequireOriginDep, SessionDep, SettingsDep
from app.core.errors import UnprocessableError
from app.schemas.posts import (
    CancelScheduledPost,
    CreateScheduledPost,
    ScheduledPostListResponse,
    ScheduledPostResponse,
    UpdateScheduledPost,
)
from app.services.posts import PostService

router = APIRouter(prefix="/posts", tags=["posts"])


@router.post("", response_model=ScheduledPostResponse, status_code=201)
async def create_post(
    body: CreateScheduledPost,
    user: CurrentUserDep,
    session: SessionDep,
    settings: SettingsDep,
    _: RequireOriginDep,
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> ScheduledPostResponse:
    if not idempotency_key:
        raise UnprocessableError("Idempotency-Key header is required.")
    return await PostService(session, settings=settings).create(
        user=user,
        payload=body,
        idempotency_key=idempotency_key,
    )


@router.get("", response_model=ScheduledPostListResponse)
async def list_posts(
    user: CurrentUserDep,
    session: SessionDep,
    settings: SettingsDep,
    status: Annotated[str | None, Query()] = None,
    scheduled_from: Annotated[datetime | None, Query()] = None,
    scheduled_to: Annotated[datetime | None, Query()] = None,
    cursor: Annotated[str | None, Query()] = None,
    limit: Annotated[int | None, Query(ge=1, le=100)] = None,
) -> ScheduledPostListResponse:
    return await PostService(session, settings=settings).list_posts(
        user=user,
        status=status,
        scheduled_from=scheduled_from,
        scheduled_to=scheduled_to,
        cursor=cursor,
        limit=limit,
    )


@router.get("/{post_id}", response_model=ScheduledPostResponse)
async def get_post(
    post_id: UUID,
    user: CurrentUserDep,
    session: SessionDep,
    settings: SettingsDep,
) -> ScheduledPostResponse:
    return await PostService(session, settings=settings).get(user=user, post_id=post_id)


@router.patch("/{post_id}", response_model=ScheduledPostResponse)
async def update_post(
    post_id: UUID,
    body: UpdateScheduledPost,
    user: CurrentUserDep,
    session: SessionDep,
    settings: SettingsDep,
    _: RequireOriginDep,
) -> ScheduledPostResponse:
    return await PostService(session, settings=settings).update(
        user=user,
        post_id=post_id,
        payload=body,
    )


@router.post("/{post_id}/cancel", response_model=ScheduledPostResponse)
async def cancel_post(
    post_id: UUID,
    body: CancelScheduledPost,
    user: CurrentUserDep,
    session: SessionDep,
    settings: SettingsDep,
    _: RequireOriginDep,
) -> ScheduledPostResponse:
    return await PostService(session, settings=settings).cancel(
        user=user,
        post_id=post_id,
        expected_version=body.expected_version,
    )
