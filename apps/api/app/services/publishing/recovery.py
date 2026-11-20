"""Recover processing posts whose leases expired without a final outcome."""

from __future__ import annotations

from datetime import UTC, datetime

import structlog
from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.models import PublishAttempt, ScheduledPost
from app.models.enums import AttemptExecutionState, PostStatus
from app.services.publishing.metrics import METRICS

logger = structlog.get_logger(__name__)


class RecoveryService:
    def __init__(self, session: AsyncSession, *, settings: Settings) -> None:
        self._db = session
        self._settings = settings

    async def recover_expired_leases(self, *, now: datetime | None = None) -> dict[str, int]:
        clock = now or datetime.now(UTC)
        dialect = self._db.get_bind().dialect.name

        filters = [
            ScheduledPost.status == PostStatus.PROCESSING.value,
            ScheduledPost.processing_lease_until.is_not(None),
            ScheduledPost.processing_lease_until <= clock,
        ]
        stmt = select(ScheduledPost).where(and_(*filters)).order_by(ScheduledPost.id.asc())
        if dialect == "postgresql":
            stmt = stmt.with_for_update(skip_locked=True)

        result = await self._db.execute(stmt)
        posts = list(result.scalars().all())
        requeued = 0
        reviewed = 0

        for post in posts:
            action = await self._recover_one(post, clock=clock)
            if action == "requeued":
                requeued += 1
            elif action == "requires_review":
                reviewed += 1

        await self._db.commit()
        logger.info(
            "publish.recovery.scan",
            expired_count=len(posts),
            requeued=requeued,
            requires_review=reviewed,
        )
        return {"expired": len(posts), "requeued": requeued, "requires_review": reviewed}

    async def _recover_one(self, post: ScheduledPost, *, clock: datetime) -> str:
        attempt = await self._load_current_attempt(post)
        if attempt is None:
            # No durable attempt → safe to return to scheduled.
            return self._requeue(post, clock=clock, code="recovery_missing_attempt")

        state = attempt.execution_state
        if state == AttemptExecutionState.CLAIMED.value and attempt.request_started_at is None:
            # Submission never began.
            attempt.execution_state = AttemptExecutionState.INTERRUPTED.value
            attempt.finished_at = clock
            attempt.sanitized_error_code = "recovery_pre_submission"
            attempt.error_category = "recovery"
            attempt.updated_at = clock
            return self._requeue(post, clock=clock, code="recovery_pre_submission")

        if state in {
            AttemptExecutionState.SUCCEEDED.value,
            AttemptExecutionState.PERMANENT_FAILURE.value,
            AttemptExecutionState.RETRYABLE_FAILURE.value,
            AttemptExecutionState.AMBIGUOUS.value,
        }:
            # Final attempt state already written; align post if needed.
            if state == AttemptExecutionState.SUCCEEDED.value:
                post.status = PostStatus.PUBLISHED.value
                post.published_at = attempt.finished_at or clock
                post.linkedin_post_urn = attempt.provider_post_urn
                post.current_attempt_id = None
                post.processing_lease_until = None
                post.updated_at = clock
                post.version += 1
                return "aligned"
            if state == AttemptExecutionState.RETRYABLE_FAILURE.value:
                post.status = PostStatus.SCHEDULED.value
                post.next_attempt_at = attempt.next_retry_at
                post.current_attempt_id = None
                post.processing_lease_until = None
                post.updated_at = clock
                post.version += 1
                return "aligned"
            if state == AttemptExecutionState.PERMANENT_FAILURE.value:
                post.status = PostStatus.FAILED.value
                post.current_attempt_id = None
                post.processing_lease_until = None
                post.updated_at = clock
                post.version += 1
                return "aligned"
            post.status = PostStatus.REQUIRES_REVIEW.value
            post.current_attempt_id = None
            post.processing_lease_until = None
            post.updated_at = clock
            post.version += 1
            return "aligned"

        # SUBMITTING / INTERRUPTED / anything after request may have started → review.
        attempt.execution_state = AttemptExecutionState.AMBIGUOUS.value
        attempt.finished_at = clock
        attempt.error_category = "recovery"
        attempt.sanitized_error_code = "recovery_ambiguous_after_submission"
        attempt.updated_at = clock

        post.status = PostStatus.REQUIRES_REVIEW.value
        post.current_attempt_id = None
        post.processing_lease_until = None
        post.dispatch_lease_until = None
        post.next_attempt_at = None
        post.last_error_code = "recovery_ambiguous_after_submission"
        post.last_error_at = clock
        post.updated_at = clock
        post.version += 1
        METRICS.incr("recoveries_requires_review")
        METRICS.incr("uncertain_outcomes")
        logger.info(
            "publish.recovery.requires_review",
            post_id=str(post.id),
            attempt_id=str(attempt.id),
        )
        return "requires_review"

    def _requeue(self, post: ScheduledPost, *, clock: datetime, code: str) -> str:
        post.status = PostStatus.SCHEDULED.value
        post.current_attempt_id = None
        post.processing_lease_until = None
        post.dispatch_lease_until = None
        post.next_attempt_at = clock
        post.last_error_code = code
        post.last_error_at = clock
        post.updated_at = clock
        post.version += 1
        METRICS.incr("recoveries_requeued")
        logger.info("publish.recovery.requeued", post_id=str(post.id), code=code)
        return "requeued"

    async def _load_current_attempt(self, post: ScheduledPost) -> PublishAttempt | None:
        if post.current_attempt_id is None:
            # Fall back to latest attempt for this post.
            result = await self._db.execute(
                select(PublishAttempt)
                .where(PublishAttempt.post_id == post.id)
                .order_by(PublishAttempt.attempt_number.desc())
                .limit(1)
            )
            return result.scalar_one_or_none()
        result = await self._db.execute(
            select(PublishAttempt).where(
                PublishAttempt.post_id == post.id,
                PublishAttempt.fencing_token == post.current_attempt_id,
            )
        )
        return result.scalar_one_or_none()
