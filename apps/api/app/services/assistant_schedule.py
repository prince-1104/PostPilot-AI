"""Phase 5C: explicit draft → PostService scheduling (LLM never calls this)."""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

import structlog
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.errors import (
    ForbiddenError,
    InvalidStateError,
    NotFoundError,
    UnprocessableError,
    VersionConflictError,
)
from app.models import AgentDraft, AgentDraftScheduleOp, AgentThread, User
from app.models.enums import AgentDraftScheduleOpState, AgentDraftStatus, AssistantResponseState
from app.schemas.assistant import (
    AssistantScheduleConfirmRequest,
    AssistantScheduleConfirmResponse,
    AssistantSchedulePreviewRequest,
    AssistantSchedulePreviewResponse,
)
from app.schemas.posts import CreateScheduledPost
from app.services.posts import PostService

logger = structlog.get_logger(__name__)


class DraftScheduleService:
    def __init__(self, session: AsyncSession, *, settings: Settings) -> None:
        self._db = session
        self._settings = settings
        self._posts = PostService(session, settings=settings)

    async def preview(
        self,
        *,
        user: User,
        draft_id: UUID,
        payload: AssistantSchedulePreviewRequest,
    ) -> AssistantSchedulePreviewResponse:
        thread, draft = await self._require_owned_draft(user_id=user.id, draft_id=draft_id)
        self._assert_draft_version(draft, payload.expected_draft_version)
        content = (payload.content or draft.content).strip()
        hard, advisory = self._collect_warnings(thread=thread, draft=draft, content=content)

        connection = None
        connection_warning: str | None = None
        approval_warnings: list[str] = []
        try:
            connection, approval_warnings = await self._posts.validate_schedule_inputs(
                user=user,
                content=content,
                scheduled_at=payload.scheduled_at,
                timezone=payload.timezone,
                linkedin_connection_id=payload.linkedin_connection_id,
            )
            if approval_warnings:
                connection_warning = approval_warnings[0]
        except (UnprocessableError, ForbiddenError) as exc:
            hard.append(exc.message)

        if draft.scheduled_post_id is not None and draft.status == AgentDraftStatus.SCHEDULED.value:
            hard.append(
                "This draft version is already linked to a scheduled post. "
                "Edit the draft to create a new version, or manage the post in Posts."
            )

        needs_ack = bool(advisory) and not payload.acknowledge_warnings
        if needs_ack:
            hard.append(
                "Acknowledge advisory review warnings before confirming this schedule."
            )

        can_confirm = len(hard) == 0
        local = _format_local(payload.scheduled_at, payload.timezone)
        return AssistantSchedulePreviewResponse(
            draft_id=draft.id,
            draft_version=draft.version,
            content=content,
            linkedin_connection_id=payload.linkedin_connection_id,
            linkedin_display_name=(
                connection.provider_subject if connection is not None else None
            ),
            scheduled_at_local=local,
            timezone=payload.timezone,
            scheduled_at_utc=payload.scheduled_at.astimezone(UTC),
            approval_warnings=approval_warnings,
            advisory_warnings=advisory,
            hard_blockers=hard,
            connection_expiry_warning=connection_warning,
            can_confirm=can_confirm,
        )

    async def confirm(
        self,
        *,
        user: User,
        draft_id: UUID,
        payload: AssistantScheduleConfirmRequest,
        idempotency_key: str,
    ) -> AssistantScheduleConfirmResponse:
        # Explicit confirmation only — never inferred from chat text / LLM.
        if payload.confirm_schedule is not True:
            raise UnprocessableError("confirm_schedule must be true.")

        thread, draft = await self._lock_owned_draft(user_id=user.id, draft_id=draft_id)
        self._assert_draft_version(draft, payload.expected_draft_version)

        # Idempotent replay for the same confirmation key.
        existing_op = await self._get_op_by_idempotency(
            user_id=user.id, idempotency_key=idempotency_key
        )
        if existing_op is not None:
            return await self._recover_or_replay(user=user, op=existing_op)

        content = payload.content.strip()
        hard, advisory = self._collect_warnings(thread=thread, draft=draft, content=content)
        if hard:
            raise UnprocessableError("; ".join(hard))
        if advisory and not payload.acknowledge_warnings:
            raise UnprocessableError(
                "Acknowledge advisory review warnings before confirming this schedule."
            )
        if draft.scheduled_post_id is not None and draft.status == AgentDraftStatus.SCHEDULED.value:
            raise InvalidStateError(
                "This draft version is already scheduled. Create a new draft version to "
                "schedule again."
            )

        # Validate through PostService rules (connection ownership included).
        await self._posts.validate_schedule_inputs(
            user=user,
            content=content,
            scheduled_at=payload.scheduled_at,
            timezone=payload.timezone,
            linkedin_connection_id=payload.linkedin_connection_id,
        )

        content_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()
        now = datetime.now(UTC)
        op = AgentDraftScheduleOp(
            id=uuid4(),
            draft_id=draft.id,
            draft_version=draft.version,
            user_id=user.id,
            content_snapshot=content,
            content_hash=content_hash,
            linkedin_connection_id=payload.linkedin_connection_id,
            scheduled_at=payload.scheduled_at.astimezone(UTC),
            timezone=payload.timezone,
            scheduled_post_id=None,
            idempotency_key=idempotency_key,
            state=AgentDraftScheduleOpState.PENDING.value,
            warnings_acknowledged=bool(payload.acknowledge_warnings),
            advisory_warnings=list(advisory),
            created_at=now,
            confirmed_at=None,
        )
        self._db.add(op)
        try:
            await self._db.flush()
        except IntegrityError as exc:
            await self._db.rollback()
            raced = await self._get_op_by_idempotency(
                user_id=user.id, idempotency_key=idempotency_key
            )
            if raced is not None:
                return await self._recover_or_replay(user=user, op=raced)
            raise UnprocessableError(
                "Could not start schedule confirmation (possible concurrent request)."
            ) from exc

        # PostService.create commits its own transaction — linkage is recovered via key.
        create_payload = CreateScheduledPost(
            content=content,
            scheduled_at=payload.scheduled_at,
            timezone=payload.timezone,
            linkedin_connection_id=payload.linkedin_connection_id,
            confirm_publish=True,
        )
        try:
            post = await self._posts.create(
                user=user,
                payload=create_payload,
                idempotency_key=idempotency_key,
            )
        except Exception:
            # Reload session state after PostService rollback/commit paths.
            await self._db.rollback()
            op_row = await self._get_op_by_idempotency(
                user_id=user.id, idempotency_key=idempotency_key
            )
            if op_row is not None:
                op_row.state = AgentDraftScheduleOpState.FAILED.value
                await self._db.commit()
            raise

        return await self._link_confirmed(user=user, op_id=op.id, post_id=post.id)

    async def _link_confirmed(
        self, *, user: User, op_id: UUID, post_id: UUID
    ) -> AssistantScheduleConfirmResponse:
        op = (
            await self._db.execute(
                select(AgentDraftScheduleOp).where(AgentDraftScheduleOp.id == op_id)
            )
        ).scalar_one()
        draft = (
            await self._db.execute(select(AgentDraft).where(AgentDraft.id == op.draft_id))
        ).scalar_one()
        now = datetime.now(UTC)
        op.scheduled_post_id = post_id
        op.state = AgentDraftScheduleOpState.CONFIRMED.value
        op.confirmed_at = now
        draft.scheduled_post_id = post_id
        draft.status = AgentDraftStatus.SCHEDULED.value
        draft.updated_at = now
        await self._db.commit()

        post = await self._posts.get(user=user, post_id=post_id)
        logger.info(
            "assistant.draft_scheduled",
            draft_id=str(draft.id),
            post_id=str(post_id),
            user_id=str(user.id),
            draft_version=draft.version,
        )
        return AssistantScheduleConfirmResponse(
            draft_id=draft.id,
            draft_version=draft.version,
            scheduled_post_id=post_id,
            post=post,
            idempotent_replay=False,
        )

    async def _recover_or_replay(
        self, *, user: User, op: AgentDraftScheduleOp
    ) -> AssistantScheduleConfirmResponse:
        if (
            op.state == AgentDraftScheduleOpState.CONFIRMED.value
            and op.scheduled_post_id is not None
        ):
            post = await self._posts.get(user=user, post_id=op.scheduled_post_id)
            return AssistantScheduleConfirmResponse(
                draft_id=op.draft_id,
                draft_version=op.draft_version,
                scheduled_post_id=op.scheduled_post_id,
                post=post,
                idempotent_replay=True,
            )

        # Pending/failed with PostService already committed: recover via same idempotency key.
        from app.repositories.posts import PostRepository

        repo = PostRepository(self._db)
        existing = await repo.get_by_idempotency_key(
            user_id=user.id, idempotency_key=op.idempotency_key
        )
        if existing is not None:
            return await self._link_confirmed(user=user, op_id=op.id, post_id=existing.id)

        if op.state == AgentDraftScheduleOpState.FAILED.value:
            raise UnprocessableError(
                "Previous schedule confirmation failed. Retry with a new Idempotency-Key "
                "after fixing the error."
            )
        raise UnprocessableError(
            "Schedule confirmation is still pending and no post was found. Retry the request."
        )

    def _collect_warnings(
        self, *, thread: AgentThread, draft: AgentDraft, content: str
    ) -> tuple[list[str], list[str]]:
        hard: list[str] = []
        advisory: list[str] = []
        state = (thread.graph_state or {}).get("response_state")
        stage = (thread.graph_state or {}).get("current_stage")
        if state in {
            AssistantResponseState.GENERATING.value,
            AssistantResponseState.UNAVAILABLE.value,
        }:
            hard.append("Draft is not ready to schedule yet.")
        if (
            stage in {"writing", "reviewing", "revising", "validating", "intent", "requirements"}
            and state != AssistantResponseState.DRAFT_READY.value
        ):
            hard.append("Assistant is still generating or gathering requirements.")
        if state == AssistantResponseState.ERROR.value and not content:
            hard.append("Draft is in an error state with no usable content.")
        if not content.strip():
            hard.append("Draft content is empty.")
        if len(content) > self._settings.post_content_max_length:
            hard.append(
                f"Draft exceeds {self._settings.post_content_max_length} characters."
            )

        graph = thread.graph_state or {}
        advisory.extend(str(x) for x in (graph.get("review_issues") or []) if x)
        advisory.extend(str(x) for x in (graph.get("unsupported_claims") or []) if x)
        # Deterministic publish claims remain hard failures.
        lower = content.lower()
        if any(
            token in lower
            for token in ("has been published", "scheduled successfully", "posted to linkedin")
        ):
            hard.append("Draft must not claim the post was already published or scheduled.")

        # Deduplicate while preserving order.
        hard = list(dict.fromkeys(hard))
        advisory = list(dict.fromkeys(advisory))
        return hard, advisory

    async def _require_owned_draft(
        self, *, user_id: UUID, draft_id: UUID
    ) -> tuple[AgentThread, AgentDraft]:
        result = await self._db.execute(select(AgentDraft).where(AgentDraft.id == draft_id))
        draft = result.scalar_one_or_none()
        if draft is None:
            raise NotFoundError("Assistant draft not found.")
        thread_result = await self._db.execute(
            select(AgentThread).where(AgentThread.id == draft.thread_id)
        )
        thread = thread_result.scalar_one_or_none()
        if thread is None or thread.user_id != user_id:
            raise NotFoundError("Assistant draft not found.")
        return thread, draft

    async def _lock_owned_draft(
        self, *, user_id: UUID, draft_id: UUID
    ) -> tuple[AgentThread, AgentDraft]:
        result = await self._db.execute(
            select(AgentDraft).where(AgentDraft.id == draft_id).with_for_update()
        )
        draft = result.scalar_one_or_none()
        if draft is None:
            raise NotFoundError("Assistant draft not found.")
        thread_result = await self._db.execute(
            select(AgentThread).where(AgentThread.id == draft.thread_id).with_for_update()
        )
        thread = thread_result.scalar_one_or_none()
        if thread is None or thread.user_id != user_id:
            raise NotFoundError("Assistant draft not found.")
        return thread, draft

    @staticmethod
    def _assert_draft_version(draft: AgentDraft, expected: int) -> None:
        if draft.version != expected:
            raise VersionConflictError(
                "Draft was updated elsewhere. Refresh and preview again before confirming."
            )

    async def _get_op_by_idempotency(
        self, *, user_id: UUID, idempotency_key: str
    ) -> AgentDraftScheduleOp | None:
        result = await self._db.execute(
            select(AgentDraftScheduleOp).where(
                AgentDraftScheduleOp.user_id == user_id,
                AgentDraftScheduleOp.idempotency_key == idempotency_key,
            )
        )
        return result.scalar_one_or_none()


def _format_local(scheduled_at: datetime, timezone_name: str) -> str:
    local = scheduled_at.astimezone(ZoneInfo(timezone_name))
    return local.strftime("%Y-%m-%d %H:%M %Z")
