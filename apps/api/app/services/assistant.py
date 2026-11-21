"""Phase 5A/5B assistant service — conversation + drafting only (no PostService writes)."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID, uuid4

import structlog
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
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
from app.core.errors import NotFoundError, UnprocessableError, VersionConflictError
from app.models import AgentDraft, AgentMessage, AgentThread, User
from app.models.enums import (
    AgentDraftStatus,
    AgentMessageRole,
    AgentThreadStatus,
    AssistantResponseState,
)
from app.schemas.assistant import (
    AssistantDraftAction,
    AssistantDraftResponse,
    AssistantMessageResponse,
    AssistantStatusResponse,
    AssistantThreadDetail,
    AssistantThreadSummary,
    AssistantTurnResponse,
    CreateAssistantThread,
    PatchAssistantDraft,
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
            lock_version=0,
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
                    current_stage=state.get("current_stage"),
                )
            )
        return summaries

    async def get_thread(self, *, user: User, thread_id: UUID) -> AssistantThreadDetail:
        thread = await self._require_thread(user_id=user.id, thread_id=thread_id)
        return self._thread_detail(thread)

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

        thread = await self._lock_thread(user_id=user.id, thread_id=thread_id)

        if payload.client_message_id is not None:
            replay = await self._replay_if_duplicate(
                thread=thread, client_message_id=payload.client_message_id
            )
            if replay is not None:
                return replay

        status = self.status()
        if not status.ai_ready:
            return await self._persist_unavailable_turn(
                thread=thread,
                content=payload.content,
                client_message_id=payload.client_message_id,
                message=status.message,
            )

        now = datetime.now(UTC)
        user_msg = AgentMessage(
            id=uuid4(),
            thread_id=thread.id,
            role=AgentMessageRole.USER.value,
            content=payload.content,
            client_message_id=payload.client_message_id,
            created_at=now,
        )
        self._db.add(user_msg)
        try:
            await self._db.flush()
        except IntegrityError as exc:
            await self._db.rollback()
            thread = await self._lock_thread(user_id=user.id, thread_id=thread_id)
            replay = await self._replay_if_duplicate(
                thread=thread, client_message_id=payload.client_message_id
            )
            if replay is not None:
                return replay
            raise UnprocessableError("Could not accept message.") from exc

        await self._trim_history(thread)

        base_state = state_from_snapshot(
            thread.graph_state
            or empty_state(thread_id=thread.id, user_id=user.id, timezone=payload.timezone)
        )
        if payload.timezone:
            base_state["timezone"] = payload.timezone
        if payload.tone:
            base_state["writing_style"] = payload.tone
        base_state["last_user_message"] = payload.content
        base_state["thread_id"] = str(thread.id)
        base_state["user_id"] = str(user.id)
        # Never carry secrets into the graph — ownership ids only.
        prior_snapshot = snapshot_from_state(base_state)
        prior_dump = prior_snapshot.model_dump(mode="json")

        llm = build_llm_provider(self._settings)
        try:
            final_state = await run_assistant_turn(
                llm=llm, settings=self._settings, state=base_state
            )
        except Exception:
            # Unexpected failures: restore prior graph snapshot and surface a safe error.
            thread.graph_state = prior_dump
            thread.lock_version = int(thread.lock_version or 0) + 1
            thread.updated_at = datetime.now(UTC)
            assistant_msg = AgentMessage(
                id=uuid4(),
                thread_id=thread.id,
                role=AgentMessageRole.ASSISTANT.value,
                content="The assistant hit an unexpected error. Your prior draft was preserved.",
                created_at=datetime.now(UTC),
            )
            self._db.add(assistant_msg)
            await self._db.commit()
            logger.exception(
                "assistant.turn_unexpected_error",
                thread_id=str(thread.id),
                user_id=str(user.id),
            )
            return AssistantTurnResponse(
                thread_id=thread.id,
                state=AssistantResponseState.ERROR.value,
                current_stage="error",
                assistant_message=self._message_response(assistant_msg),
                clarification_questions=[],
                draft=self._draft_response(self._latest_draft(thread))
                if self._latest_draft(thread)
                else None,
                lock_version=thread.lock_version,
                validation_errors=["unexpected_error"],
            )

        return await self._finalize_turn(
            thread=thread, final_state=final_state, title_seed=payload.content
        )

    async def apply_draft_action(
        self,
        *,
        user: User,
        thread_id: UUID,
        payload: AssistantDraftAction,
    ) -> AssistantTurnResponse:
        get_assistant_rate_limiter(self._settings.ai_rate_limit_per_minute).check(user.id)
        thread = await self._lock_thread(user_id=user.id, thread_id=thread_id)

        if payload.client_message_id is not None:
            replay = await self._replay_if_duplicate(
                thread=thread, client_message_id=payload.client_message_id
            )
            if replay is not None:
                return replay

        status = self.status()
        if not status.ai_ready:
            raise UnprocessableError(status.message)

        draft = self._latest_draft(thread)
        if draft is None and payload.action != "regenerate":
            raise UnprocessableError("No draft exists to revise yet.")
        if (
            payload.expected_version is not None
            and draft is not None
            and draft.version != payload.expected_version
        ):
            raise VersionConflictError(
                "Draft was updated elsewhere. Refresh and try again."
            )

        instruction = payload.instruction
        if payload.action == "regenerate":
            instruction = instruction or "Regenerate the LinkedIn draft from confirmed facts."
            entry = "writing"
        elif payload.action == "set_tone":
            if not payload.tone:
                raise UnprocessableError("tone is required for set_tone.")
            instruction = instruction or f"Rewrite the draft in a {payload.tone} tone."
            entry = "revise"
        else:
            if not instruction:
                raise UnprocessableError("instruction is required for rewrite.")
            entry = "revise"

        synthetic = instruction or payload.action
        now = datetime.now(UTC)
        user_msg = AgentMessage(
            id=uuid4(),
            thread_id=thread.id,
            role=AgentMessageRole.USER.value,
            content=synthetic,
            client_message_id=payload.client_message_id,
            created_at=now,
        )
        self._db.add(user_msg)
        try:
            await self._db.flush()
        except IntegrityError as exc:
            await self._db.rollback()
            thread = await self._lock_thread(user_id=user.id, thread_id=thread_id)
            replay = await self._replay_if_duplicate(
                thread=thread, client_message_id=payload.client_message_id
            )
            if replay is not None:
                return replay
            raise UnprocessableError("Could not accept draft action.") from exc

        base_state = state_from_snapshot(
            thread.graph_state or empty_state(thread_id=thread.id, user_id=user.id)
        )
        if payload.tone:
            base_state["writing_style"] = payload.tone
        base_state["refine_instruction"] = instruction
        base_state["last_user_message"] = synthetic
        base_state["intent_type"] = "refine_draft"
        base_state["thread_id"] = str(thread.id)
        base_state["user_id"] = str(user.id)
        if entry == "writing":
            # Regenerate from facts; keep prior draft until writing succeeds.
            pass

        llm = build_llm_provider(self._settings)
        final_state = await run_assistant_turn(
            llm=llm, settings=self._settings, state=base_state, entry=entry
        )
        return await self._finalize_turn(thread=thread, final_state=final_state, title_seed=None)

    async def patch_draft(
        self,
        *,
        user: User,
        thread_id: UUID,
        payload: PatchAssistantDraft,
    ) -> AssistantDraftResponse:
        thread = await self._lock_thread(user_id=user.id, thread_id=thread_id)
        draft = self._latest_draft(thread)
        if draft is None:
            raise NotFoundError("No draft exists for this thread yet.")
        if draft.version != payload.expected_version:
            raise VersionConflictError(
                "Draft was updated elsewhere. Refresh and try again."
            )
        if (
            payload.expected_lock_version is not None
            and int(thread.lock_version or 0) != payload.expected_lock_version
        ):
            raise VersionConflictError(
                "Thread was updated elsewhere. Refresh and try again."
            )

        # Manual edit: new version. Scheduled rows keep their post link; edits never
        # mutate ScheduledPost content (use PostService.update for that).
        if draft.status != AgentDraftStatus.SCHEDULED.value:
            draft.status = AgentDraftStatus.SUPERSEDED.value
        now = datetime.now(UTC)
        new_draft = AgentDraft(
            id=uuid4(),
            thread_id=thread.id,
            content=payload.content,
            category=draft.category,
            confirmed_facts=dict(draft.confirmed_facts or {}),
            suggested_details=dict(draft.suggested_details or {}),
            assumptions=dict(draft.assumptions or {})
            if isinstance(draft.assumptions, dict)
            else {"items": draft.assumptions},
            proposed_scheduled_at=draft.proposed_scheduled_at,
            timezone=draft.timezone,
            status=AgentDraftStatus.DRAFT.value,
            version=draft.version + 1,
            scheduled_post_id=None,
            created_at=now,
            updated_at=now,
        )
        self._db.add(new_draft)

        graph = dict(thread.graph_state or {})
        graph["draft_content"] = payload.content
        graph["response_state"] = AssistantResponseState.DRAFT_READY.value
        graph["current_stage"] = "draft_ready"
        thread.graph_state = graph
        thread.lock_version = int(thread.lock_version or 0) + 1
        thread.updated_at = now
        await self._db.commit()
        await self._db.refresh(new_draft)
        return self._draft_response(new_draft)

    async def _finalize_turn(
        self,
        *,
        thread: AgentThread,
        final_state: dict,
        title_seed: str | None,
    ) -> AssistantTurnResponse:
        reply_text = final_state.get("assistant_reply") or "I could not complete that turn."
        assistant_msg = AgentMessage(
            id=uuid4(),
            thread_id=thread.id,
            role=AgentMessageRole.ASSISTANT.value,
            content=reply_text,
            created_at=datetime.now(UTC),
        )
        self._db.add(assistant_msg)

        snapshot = snapshot_from_state(final_state)  # type: ignore[arg-type]
        thread.graph_state = snapshot.model_dump(mode="json")
        thread.lock_version = int(thread.lock_version or 0) + 1
        thread.updated_at = datetime.now(UTC)
        if title_seed and not thread.title:
            thread.title = title_seed.strip()[:80]

        draft_response = None
        if final_state.get("response_state") == AssistantResponseState.DRAFT_READY.value:
            draft_response = await self._persist_draft(thread=thread, snapshot=snapshot)

        await self._db.commit()
        await self._db.refresh(assistant_msg)

        logger.info(
            "assistant.turn_complete",
            thread_id=str(thread.id),
            user_id=str(thread.user_id),
            state=final_state.get("response_state"),
            stage=final_state.get("current_stage"),
        )

        return AssistantTurnResponse(
            thread_id=thread.id,
            state=final_state.get("response_state") or AssistantResponseState.ERROR.value,
            current_stage=final_state.get("current_stage"),
            assistant_message=self._message_response(assistant_msg),
            clarification_questions=list(final_state.get("clarification_questions") or []),
            draft=draft_response,
            proposed_scheduled_at=snapshot.proposed_scheduled_at,
            timezone=snapshot.timezone,
            writing_style=snapshot.writing_style,
            review_issues=list(snapshot.review_issues),
            review_suggestions=list(snapshot.review_suggestions),
            validation_errors=list(snapshot.validation_errors),
            lock_version=thread.lock_version,
        )

    async def _persist_unavailable_turn(
        self,
        *,
        thread: AgentThread,
        content: str,
        client_message_id: UUID | None,
        message: str,
    ) -> AssistantTurnResponse:
        now = datetime.now(UTC)
        user_msg = AgentMessage(
            id=uuid4(),
            thread_id=thread.id,
            role=AgentMessageRole.USER.value,
            content=content,
            client_message_id=client_message_id,
            created_at=now,
        )
        assistant_msg = AgentMessage(
            id=uuid4(),
            thread_id=thread.id,
            role=AgentMessageRole.ASSISTANT.value,
            content=message,
            created_at=now,
        )
        self._db.add_all([user_msg, assistant_msg])
        graph = dict(thread.graph_state or {})
        graph["response_state"] = AssistantResponseState.UNAVAILABLE.value
        graph["assistant_reply"] = message
        graph["current_stage"] = "error"
        thread.graph_state = graph
        thread.lock_version = int(thread.lock_version or 0) + 1
        thread.updated_at = now
        await self._db.commit()
        return AssistantTurnResponse(
            thread_id=thread.id,
            state=AssistantResponseState.UNAVAILABLE.value,
            current_stage="error",
            assistant_message=self._message_response(assistant_msg),
            clarification_questions=[],
            draft=None,
            lock_version=thread.lock_version,
        )

    async def _persist_draft(
        self, *, thread: AgentThread, snapshot: GraphSnapshot
    ) -> AssistantDraftResponse:
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
            suggested_details={
                "hashtags": list(snapshot.suggested_hashtags),
                "skills": list(snapshot.suggested_skills),
                "responsibilities": list(snapshot.suggested_responsibilities),
            },
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
        thread.drafts.append(draft)
        return self._draft_response(draft)

    async def _lock_thread(self, *, user_id: UUID, thread_id: UUID) -> AgentThread:
        result = await self._db.execute(
            select(AgentThread).where(AgentThread.id == thread_id).with_for_update()
        )
        thread = result.scalar_one_or_none()
        if thread is None or thread.user_id != user_id:
            raise NotFoundError("Assistant thread not found.")
        return thread

    async def _require_thread(self, *, user_id: UUID, thread_id: UUID) -> AgentThread:
        result = await self._db.execute(
            select(AgentThread).where(AgentThread.id == thread_id)
        )
        thread = result.scalar_one_or_none()
        if thread is None or thread.user_id != user_id:
            raise NotFoundError("Assistant thread not found.")
        return thread

    async def _trim_history(self, thread: AgentThread) -> None:
        prior = list(thread.messages)
        overflow = len(prior) + 1 - self._settings.ai_max_history_messages
        if overflow > 0:
            for old in prior[:overflow]:
                await self._db.delete(old)

    async def _replay_if_duplicate(
        self, *, thread: AgentThread, client_message_id: UUID | None
    ) -> AssistantTurnResponse | None:
        if client_message_id is None:
            return None
        existing = next(
            (
                m
                for m in thread.messages
                if m.client_message_id == client_message_id
                and m.role == AgentMessageRole.USER.value
            ),
            None,
        )
        if existing is None:
            return None
        # Find the next assistant message after this user turn.
        assistant = next(
            (
                m
                for m in thread.messages
                if m.role == AgentMessageRole.ASSISTANT.value
                and m.created_at >= existing.created_at
                and m.id != existing.id
            ),
            None,
        )
        state = thread.graph_state or {}
        draft = self._latest_draft(thread)
        return AssistantTurnResponse(
            thread_id=thread.id,
            state=state.get("response_state") or AssistantResponseState.DRAFT_READY.value,
            current_stage=state.get("current_stage"),
            assistant_message=self._message_response(assistant) if assistant else None,
            clarification_questions=list(state.get("clarification_questions") or []),
            draft=self._draft_response(draft) if draft else None,
            proposed_scheduled_at=None,
            timezone=state.get("timezone"),
            writing_style=state.get("writing_style"),
            review_issues=list(state.get("review_issues") or []),
            review_suggestions=list(state.get("review_suggestions") or []),
            validation_errors=list(state.get("validation_errors") or []),
            lock_version=int(thread.lock_version or 0),
            idempotent_replay=True,
        )

    def _thread_detail(self, thread: AgentThread) -> AssistantThreadDetail:
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
            current_stage=state.get("current_stage"),
            writing_style=state.get("writing_style"),
            review_issues=list(state.get("review_issues") or []),
            review_suggestions=list(state.get("review_suggestions") or []),
            validation_errors=list(state.get("validation_errors") or []),
            lock_version=int(thread.lock_version or 0),
            assistant_ready=self._settings.ai_ready,
        )

    @staticmethod
    def _latest_draft(thread: AgentThread) -> AgentDraft | None:
        # Prefer an editable draft; otherwise surface the latest scheduled version.
        editable = [
            d for d in thread.drafts if d.status == AgentDraftStatus.DRAFT.value
        ]
        if editable:
            return max(editable, key=lambda d: d.version)
        visible = [
            d
            for d in thread.drafts
            if d.status
            in {AgentDraftStatus.DRAFT.value, AgentDraftStatus.SCHEDULED.value}
        ]
        if not visible:
            return None
        return max(visible, key=lambda d: d.version)

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
        scheduled = draft.scheduled_post_id is not None
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
            scheduled_post_id=draft.scheduled_post_id,
            label="Scheduled" if scheduled else "Draft — not scheduled",
            created_at=draft.created_at,
            updated_at=draft.updated_at,
        )
