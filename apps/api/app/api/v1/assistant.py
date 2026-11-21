"""Authenticated AI assistant routes (Phase 5A — drafting only)."""

from uuid import UUID

from fastapi import APIRouter

from app.api.deps import CurrentUserDep, RequireOriginDep, SessionDep, SettingsDep
from app.schemas.assistant import (
    AssistantDraftResponse,
    AssistantStatusResponse,
    AssistantThreadDetail,
    AssistantThreadSummary,
    AssistantTurnResponse,
    CreateAssistantThread,
    PostAssistantMessage,
)
from app.services.assistant import AssistantService

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
