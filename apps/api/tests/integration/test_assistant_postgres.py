"""PostgreSQL integration for Phase 5A assistant persistence (fake LLM)."""

from __future__ import annotations

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
from app.schemas.assistant import CreateAssistantThread, PostAssistantMessage
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
    assert "published" not in (result.get("assistant_reply") or "").lower()
