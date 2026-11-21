"""Authenticated AI assistant routes (Phase 5A-5C).

Scheduling confirmation is a separate authenticated endpoint that calls PostService.
Chat/message endpoints never create scheduled_posts.
"""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Header

from app.api.deps import CurrentUserDep, RequireOriginDep, SessionDep, SettingsDep
from app.core.errors import UnprocessableError
from app.schemas.assistant import (
    AssistantDraftAction,
    AssistantDraftResponse,
    AssistantScheduleConfirmRequest,
    AssistantScheduleConfirmResponse,
    AssistantSchedulePreviewRequest,
    AssistantSchedulePreviewResponse,
    AssistantStatusResponse,
    AssistantThreadDetail,
    AssistantThreadSummary,
    AssistantTurnResponse,
    CreateAssistantThread,
    PatchAssistantDraft,
    PostAssistantMessage,
)
from app.services.assistant import AssistantService
from app.services.assistant_schedule import DraftScheduleService

router = APIRouter(prefix="/assistant", tags=["assistant"])


@router.get("/status", response_model=AssistantStatusResponse)
async def assistant_status(
    user: CurrentUserDep,
    session: SessionDep,
    settings: SettingsDep,
) -> AssistantStatusResponse:
    _ = user
    return AssistantService(session, settings=settings).status()


@router.post("/threads", response_model=AssistantThreadDetail, status_code=201)
async def create_thread(
    body: CreateAssistantThread,
    user: CurrentUserDep,
    session: SessionDep,
    settings: SettingsDep,
    _: RequireOriginDep,
) -> AssistantThreadDetail:
    return await AssistantService(session, settings=settings).create_thread(
        user=user, payload=body
    )


@router.get("/threads", response_model=list[AssistantThreadSummary])
async def list_threads(
    user: CurrentUserDep,
    session: SessionDep,
    settings: SettingsDep,
) -> list[AssistantThreadSummary]:
    return await AssistantService(session, settings=settings).list_threads(user=user)


@router.get("/threads/{thread_id}", response_model=AssistantThreadDetail)
async def get_thread(
    thread_id: UUID,
    user: CurrentUserDep,
    session: SessionDep,
    settings: SettingsDep,
) -> AssistantThreadDetail:
    return await AssistantService(session, settings=settings).get_thread(
        user=user, thread_id=thread_id
    )


@router.post(
    "/threads/{thread_id}/messages",
    response_model=AssistantTurnResponse,
)
async def post_message(
    thread_id: UUID,
    body: PostAssistantMessage,
    user: CurrentUserDep,
    session: SessionDep,
    settings: SettingsDep,
    _: RequireOriginDep,
) -> AssistantTurnResponse:
    return await AssistantService(session, settings=settings).post_message(
        user=user, thread_id=thread_id, payload=body
    )


@router.get("/threads/{thread_id}/draft", response_model=AssistantDraftResponse)
async def get_draft(
    thread_id: UUID,
    user: CurrentUserDep,
    session: SessionDep,
    settings: SettingsDep,
) -> AssistantDraftResponse:
    return await AssistantService(session, settings=settings).get_draft(
        user=user, thread_id=thread_id
    )


@router.patch("/threads/{thread_id}/draft", response_model=AssistantDraftResponse)
async def patch_draft(
    thread_id: UUID,
    body: PatchAssistantDraft,
    user: CurrentUserDep,
    session: SessionDep,
    settings: SettingsDep,
    _: RequireOriginDep,
) -> AssistantDraftResponse:
    return await AssistantService(session, settings=settings).patch_draft(
        user=user, thread_id=thread_id, payload=body
    )


@router.post(
    "/threads/{thread_id}/draft/actions",
    response_model=AssistantTurnResponse,
)
async def draft_action(
    thread_id: UUID,
    body: AssistantDraftAction,
    user: CurrentUserDep,
    session: SessionDep,
    settings: SettingsDep,
    _: RequireOriginDep,
) -> AssistantTurnResponse:
    return await AssistantService(session, settings=settings).apply_draft_action(
        user=user, thread_id=thread_id, payload=body
    )


@router.post(
    "/drafts/{draft_id}/schedule-preview",
    response_model=AssistantSchedulePreviewResponse,
)
async def schedule_preview(
    draft_id: UUID,
    body: AssistantSchedulePreviewRequest,
    user: CurrentUserDep,
    session: SessionDep,
    settings: SettingsDep,
    _: RequireOriginDep,
) -> AssistantSchedulePreviewResponse:
    return await DraftScheduleService(session, settings=settings).preview(
        user=user, draft_id=draft_id, payload=body
    )


@router.post(
    "/drafts/{draft_id}/schedule",
    response_model=AssistantScheduleConfirmResponse,
    status_code=201,
)
async def schedule_confirm(
    draft_id: UUID,
    body: AssistantScheduleConfirmRequest,
    user: CurrentUserDep,
    session: SessionDep,
    settings: SettingsDep,
    _: RequireOriginDep,
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> AssistantScheduleConfirmResponse:
    if not idempotency_key:
        raise UnprocessableError("Idempotency-Key header is required.")
    return await DraftScheduleService(session, settings=settings).confirm(
        user=user,
        draft_id=draft_id,
        payload=body,
        idempotency_key=idempotency_key,
    )
