"""PostgreSQL integration for Phase 5A/5B assistant persistence (fake LLM)."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from uuid import uuid4

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.assistant.graph import empty_state, run_assistant_turn
from app.assistant.llm.fake import FakeLLMProvider
from app.core.config import Settings
from app.core.security import TokenEncryptor
from app.db.session import create_engine, create_session_factory
from app.models import AgentDraft, AgentMessage, AgentThread, ScheduledPost
from app.models.enums import AgentDraftStatus, AgentThreadStatus
from app.schemas.assistant import (
    CreateAssistantThread,
    PatchAssistantDraft,
    PostAssistantMessage,
)
from app.services.assistant import AssistantService
from tests.conftest import seed_user_session_and_connection

pytestmark = pytest.mark.integration


@pytest.fixture
async def pg_factory() -> AsyncIterator[tuple[async_sessionmaker[AsyncSession], Settings]]:
    settings = Settings(
        ai_enabled=True,
        ai_provider="fake",
        ai_model="fake-model",
        publish_provider="fake",
        enable_real_publishing=False,
        live_publish_require_canary=True,
    )
    engine = create_engine(settings)
    factory = create_session_factory(engine)
    yield factory, settings
    await engine.dispose()


@pytest.mark.asyncio
async def test_conversation_and_draft_persist_without_scheduled_posts(
    pg_factory: tuple[async_sessionmaker[AsyncSession], Settings],
) -> None:
    factory, settings = pg_factory
    encryptor = TokenEncryptor.from_settings_value(settings.token_encryption_key)
    async with factory() as session:
        user, _raw, _conn = await seed_user_session_and_connection(
            session, encryptor=encryptor, subject=f"pg-asst-{uuid4()}"
        )
        service = AssistantService(session, settings=settings)
        thread = await service.create_thread(
            user=user, payload=CreateAssistantThread(timezone="UTC")
        )
        turn = await service.post_message(
            user=user,
            thread_id=thread.id,
            payload=PostAssistantMessage(
                content=(
                    "Hiring Backend Engineer. Company is Acme. Remote. 4 years experience."
                ),
                timezone="UTC",
            ),
        )
        assert turn.state == "draft_ready"
        assert turn.draft is not None

        messages = (
            await session.execute(
                select(func.count()).select_from(AgentMessage).where(
                    AgentMessage.thread_id == thread.id
                )
            )
        ).scalar_one()
        drafts = (
            await session.execute(
                select(func.count()).select_from(AgentDraft).where(
                    AgentDraft.thread_id == thread.id,
                    AgentDraft.status == AgentDraftStatus.DRAFT.value,
                )
            )
        ).scalar_one()
        posts = (
            await session.execute(
                select(func.count()).select_from(ScheduledPost).where(
                    ScheduledPost.user_id == user.id
                )
            )
        ).scalar_one()
        row = (
            await session.execute(select(AgentThread).where(AgentThread.id == thread.id))
        ).scalar_one()
        assert messages >= 2
        assert drafts == 1
        assert posts == 0
        assert row.status == AgentThreadStatus.ACTIVE.value
        assert row.graph_state.get("response_state") == "draft_ready"
        assert int(row.lock_version or 0) >= 1


@pytest.mark.asyncio
async def test_manual_edit_and_concurrent_turns_safe(
    pg_factory: tuple[async_sessionmaker[AsyncSession], Settings],
) -> None:
    factory, settings = pg_factory
    encryptor = TokenEncryptor.from_settings_value(settings.token_encryption_key)
    async with factory() as session:
        user, _raw, _conn = await seed_user_session_and_connection(
            session, encryptor=encryptor, subject=f"pg-asst-conc-{uuid4()}"
        )
        user_id = user.id
        service = AssistantService(session, settings=settings)
        thread = await service.create_thread(
            user=user, payload=CreateAssistantThread(timezone="UTC")
        )
        thread_id = thread.id
        turn = await service.post_message(
            user=user,
            thread_id=thread_id,
            payload=PostAssistantMessage(
                content=(
                    "Hiring Backend Engineer. Company is Acme. Remote. 4 years experience."
                ),
                timezone="UTC",
                client_message_id=uuid4(),
            ),
        )
        assert turn.draft is not None
        edited = await service.patch_draft(
            user=user,
            thread_id=thread_id,
            payload=PatchAssistantDraft(
                content="Edited Acme draft for Postgres.",
                expected_version=turn.draft.version,
                expected_lock_version=turn.lock_version,
            ),
        )
        assert edited.content.startswith("Edited Acme")
        assert edited.version == turn.draft.version + 1

    async def _send() -> str:
        async with factory() as session:
            local = AssistantService(session, settings=settings)
            from app.models import User

            owner = (
                await session.execute(select(User).where(User.id == user_id))
            ).scalar_one()
            result = await local.post_message(
                user=owner,
                thread_id=thread_id,
                payload=PostAssistantMessage(
                    content="Make it shorter and more professional.",
                    timezone="UTC",
                    client_message_id=uuid4(),
                ),
            )
            return result.state

    states = await asyncio.gather(_send(), _send())
    assert all(state in {"draft_ready", "error", "needs_information"} for state in states)

    async with factory() as session:
        messages = (
            await session.execute(
                select(func.count()).select_from(AgentMessage).where(
                    AgentMessage.thread_id == thread_id,
                    AgentMessage.role == "user",
                )
            )
        ).scalar_one()
        posts = (
            await session.execute(
                select(func.count()).select_from(ScheduledPost).where(
                    ScheduledPost.user_id == user_id
                )
            )
        ).scalar_one()
        assert messages >= 3  # original + two concurrent refine attempts
        assert posts == 0


@pytest.mark.asyncio
async def test_graph_does_not_create_publish_side_effects(
    pg_factory: tuple[async_sessionmaker[AsyncSession], Settings],
) -> None:
    _factory, settings = pg_factory
    llm = FakeLLMProvider()
    state = empty_state(thread_id=uuid4(), user_id=uuid4(), timezone="UTC")
    state["last_user_message"] = (
        "Hiring Backend Engineer. Company is Acme. Remote. 4 years experience."
    )
    result = await run_assistant_turn(llm=llm, settings=settings, state=state)
    assert result["response_state"] == "draft_ready"
    reply = (result.get("assistant_reply") or "").lower()
    assert "has been published" not in reply
    assert "scheduled successfully" not in reply
