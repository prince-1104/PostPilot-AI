"""Phase 5A assistant service — conversation + drafting only (no PostService writes)."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID, uuid4

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.assistant.graph import (
    empty_state,
    run_assistant_turn,
    snapshot_from_state,
    state_from_snapshot,
)
from app.assistant.llm.factory import build_llm_provider
from app.assistant.rate_limit import get_assistant_rate_limiter
from app.assistant.schemas import GraphSnapshot
from app.core.config import Settings
from app.core.errors import NotFoundError, UnprocessableError
from app.models import AgentDraft, AgentMessage, AgentThread, User
from app.models.enums import (
    AgentDraftStatus,
    AgentMessageRole,
    AgentThreadStatus,
    AssistantResponseState,
)
from app.schemas.assistant import (
    AssistantDraftResponse,
    AssistantMessageResponse,
    AssistantStatusResponse,
    AssistantThreadDetail,
    AssistantThreadSummary,
    AssistantTurnResponse,
    CreateAssistantThread,
    PostAssistantMessage,
)

logger = structlog.get_logger(__name__)


class AssistantService:
    def __init__(self, session: AsyncSession, *, settings: Settings) -> None:
        self._db = session
        self._settings = settings

    def status(self) -> AssistantStatusResponse:
        if not self._settings.ai_enabled:
            return AssistantStatusResponse(
                ai_enabled=False,
                ai_ready=False,
                provider=self._settings.ai_provider,
                model=None,
                message=(
                    "AI assistant is turned off. Set AI_ENABLED=true and configure "
                    "AI_PROVIDER / OPENAI_API_KEY (and AI_MODEL) to enable drafting."
                ),
            )
        if not self._settings.ai_ready:
            return AssistantStatusResponse(
                ai_enabled=True,
                ai_ready=False,
                provider=self._settings.ai_provider,
                model=self._settings.ai_model,
                message=(
                    "AI is enabled but not fully configured. For OpenAI, set a non-empty "
                    "OPENAI_API_KEY and a valid AI_MODEL."
                ),
            )
        return AssistantStatusResponse(
            ai_enabled=True,
            ai_ready=True,
            provider=self._settings.ai_provider,
            model=self._settings.ai_model,
            message="AI assistant is ready for draft conversations.",
        )

    async def create_thread(
        self, *, user: User, payload: CreateAssistantThread
    ) -> AssistantThreadDetail:
        now = datetime.now(UTC)
        thread_id = uuid4()
        thread = AgentThread(
            id=thread_id,
            user_id=user.id,
            status=AgentThreadStatus.ACTIVE.value,
            title=payload.title,
            graph_state=dict(
                empty_state(thread_id=thread_id, user_id=user.id, timezone=payload.timezone)
            ),
            created_at=now,
            updated_at=now,
        )
        self._db.add(thread)
        await self._db.commit()
        await self._db.refresh(thread)
        return await self.get_thread(user=user, thread_id=thread.id)

    async def list_threads(self, *, user: User) -> list[AssistantThreadSummary]:
        result = await self._db.execute(
            select(AgentThread)
            .where(
                AgentThread.user_id == user.id,
                AgentThread.status == AgentThreadStatus.ACTIVE.value,
            )
            .order_by(AgentThread.updated_at.desc())
            .limit(50)
        )
        threads = list(result.scalars().all())
        summaries: list[AssistantThreadSummary] = []
        for thread in threads:
            state = thread.graph_state or {}
            summaries.append(
                AssistantThreadSummary(
                    id=thread.id,
                    status=thread.status,
                    title=thread.title,
                    created_at=thread.created_at,
                    updated_at=thread.updated_at,
                    response_state=state.get("response_state"),
                )
            )
        return summaries

    async def get_thread(self, *, user: User, thread_id: UUID) -> AssistantThreadDetail:
        thread = await self._require_thread(user_id=user.id, thread_id=thread_id)
        draft = self._latest_draft(thread)
        state = thread.graph_state or {}
        return AssistantThreadDetail(
            id=thread.id,
            status=thread.status,
            title=thread.title,
            created_at=thread.created_at,
            updated_at=thread.updated_at,
            messages=[self._message_response(m) for m in thread.messages],
            draft=self._draft_response(draft) if draft else None,
            clarification_questions=list(state.get("clarification_questions") or []),
            response_state=state.get("response_state") or AssistantResponseState.GENERATING.value,
            assistant_ready=self._settings.ai_ready,
        )

    async def get_draft(self, *, user: User, thread_id: UUID) -> AssistantDraftResponse:
        thread = await self._require_thread(user_id=user.id, thread_id=thread_id)
        draft = self._latest_draft(thread)
        if draft is None:
            raise NotFoundError("No draft exists for this thread yet.")
        return self._draft_response(draft)

    async def post_message(
        self,
        *,
        user: User,
        thread_id: UUID,
        payload: PostAssistantMessage,
    ) -> AssistantTurnResponse:
        if len(payload.content) > self._settings.ai_max_user_message_chars:
            raise UnprocessableError(
                f"Message must be at most {self._settings.ai_max_user_message_chars} characters."
            )

        get_assistant_rate_limiter(self._settings.ai_rate_limit_per_minute).check(user.id)

        status = self.status()
        if not status.ai_ready:
            thread = await self._require_thread(user_id=user.id, thread_id=thread_id)
            now = datetime.now(UTC)
            user_msg = AgentMessage(
                id=uuid4(),
                thread_id=thread.id,
                role=AgentMessageRole.USER.value,
                content=payload.content,
                created_at=now,
            )
            assistant_msg = AgentMessage(
                id=uuid4(),
                thread_id=thread.id,
                role=AgentMessageRole.ASSISTANT.value,
                content=status.message,
                created_at=now,
            )
            self._db.add_all([user_msg, assistant_msg])
            thread.updated_at = now
            graph = dict(thread.graph_state or {})
            graph["response_state"] = AssistantResponseState.UNAVAILABLE.value
            graph["assistant_reply"] = status.message
            thread.graph_state = graph
            await self._db.commit()
            return AssistantTurnResponse(
                thread_id=thread.id,
                state=AssistantResponseState.UNAVAILABLE.value,
                assistant_message=self._message_response(assistant_msg),
                clarification_questions=[],
                draft=None,
            )

        thread = await self._require_thread(user_id=user.id, thread_id=thread_id)
        now = datetime.now(UTC)
        user_msg = AgentMessage(
            id=uuid4(),
            thread_id=thread.id,
            role=AgentMessageRole.USER.value,
            content=payload.content,
            created_at=now,
        )
        self._db.add(user_msg)

        # Bound history in DB (keep newest N including this message after commit).
        prior = list(thread.messages)
        overflow = len(prior) + 1 - self._settings.ai_max_history_messages
        if overflow > 0:
            for old in prior[:overflow]:
                await self._db.delete(old)

        base_state = state_from_snapshot(thread.graph_state or empty_state(
            thread_id=thread.id, user_id=user.id, timezone=payload.timezone
        ))
        if payload.timezone:
            base_state["timezone"] = payload.timezone
        base_state["last_user_message"] = payload.content
        base_state["thread_id"] = str(thread.id)
        base_state["user_id"] = str(user.id)

        llm = build_llm_provider(self._settings)
        final_state = await run_assistant_turn(
            llm=llm, settings=self._settings, state=base_state
        )

        reply_text = final_state.get("assistant_reply") or "I could not complete that turn."
        assistant_msg = AgentMessage(
            id=uuid4(),
            thread_id=thread.id,
            role=AgentMessageRole.ASSISTANT.value,
            content=reply_text,
            created_at=datetime.now(UTC),
        )
        self._db.add(assistant_msg)

        snapshot = snapshot_from_state(final_state)
        thread.graph_state = snapshot.model_dump(mode="json")
        thread.updated_at = datetime.now(UTC)
        if not thread.title:
            thread.title = payload.content.strip()[:80]

        draft_response = None
        if final_state.get("response_state") == AssistantResponseState.DRAFT_READY.value:
            draft_response = await self._persist_draft(thread=thread, snapshot=snapshot)

        await self._db.commit()
        await self._db.refresh(assistant_msg)

        logger.info(
            "assistant.turn_complete",
            thread_id=str(thread.id),
            user_id=str(user.id),
            state=final_state.get("response_state"),
            stage=final_state.get("current_stage"),
        )

        return AssistantTurnResponse(
            thread_id=thread.id,
            state=final_state.get("response_state") or AssistantResponseState.ERROR.value,
            assistant_message=self._message_response(assistant_msg),
            clarification_questions=list(final_state.get("clarification_questions") or []),
            draft=draft_response,
            proposed_scheduled_at=snapshot.proposed_scheduled_at,
            timezone=snapshot.timezone,
        )

    async def _persist_draft(
        self, *, thread: AgentThread, snapshot: GraphSnapshot
    ) -> AssistantDraftResponse:
        # Supersede previous active drafts.
        for existing in thread.drafts:
            if existing.status == AgentDraftStatus.DRAFT.value:
                existing.status = AgentDraftStatus.SUPERSEDED.value
        version = max((d.version for d in thread.drafts), default=0) + 1
        now = datetime.now(UTC)
        draft = AgentDraft(
            id=uuid4(),
            thread_id=thread.id,
            content=snapshot.draft_content or "",
            category=snapshot.post_category,
            confirmed_facts=dict(snapshot.confirmed_facts),
            suggested_details={"hashtags": list(snapshot.suggested_hashtags)},
            assumptions={"items": list(snapshot.assumptions)},
            proposed_scheduled_at=snapshot.proposed_scheduled_at,
            timezone=snapshot.timezone,
            status=AgentDraftStatus.DRAFT.value,
            version=version,
            created_at=now,
            updated_at=now,
        )
        self._db.add(draft)
        await self._db.flush()
        return self._draft_response(draft)

    async def _require_thread(self, *, user_id: UUID, thread_id: UUID) -> AgentThread:
        result = await self._db.execute(
            select(AgentThread).where(AgentThread.id == thread_id)
        )
        thread = result.scalar_one_or_none()
        if thread is None or thread.user_id != user_id:
            # Same message for missing vs other-user — do not leak ownership.
            raise NotFoundError("Assistant thread not found.")
        return thread

    @staticmethod
    def _latest_draft(thread: AgentThread) -> AgentDraft | None:
        active = [
            d for d in thread.drafts if d.status == AgentDraftStatus.DRAFT.value
        ]
        if not active:
            return None
        return max(active, key=lambda d: d.version)

    @staticmethod
    def _message_response(message: AgentMessage) -> AssistantMessageResponse:
        return AssistantMessageResponse(
            id=message.id,
            role=message.role,
            content=message.content,
            created_at=message.created_at,
        )

    @staticmethod
    def _draft_response(draft: AgentDraft) -> AssistantDraftResponse:
        return AssistantDraftResponse(
            id=draft.id,
            content=draft.content,
            category=draft.category,
            confirmed_facts=dict(draft.confirmed_facts or {}),
            suggested_details=dict(draft.suggested_details or {}),
            assumptions=draft.assumptions or {},
            proposed_scheduled_at=draft.proposed_scheduled_at,
            timezone=draft.timezone,
            status=draft.status,
            version=draft.version,
            created_at=draft.created_at,
            updated_at=draft.updated_at,
        )
