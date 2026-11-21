"""Execute a claimed publish attempt with submission boundary and fencing."""

from __future__ import annotations

import time
from datetime import UTC, datetime, timedelta
from uuid import UUID

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.models import LinkedInConnection, PublishAttempt, ScheduledPost
from app.models.enums import AttemptExecutionState, ConnectionStatus, PostStatus
from app.publishing.authorization import (
    APPROVAL_DEFER_SECONDS,
    db_approval_required,
    defer_unauthorized_post,
    is_db_publish_approved,
)
from app.publishing.base import LinkedInPublisher
from app.publishing.canary import is_post_canary_approved
from app.publishing.outcomes import (
    OutcomeKind,
    PublishExecutionContext,
    PublishOutcome,
)
from app.services.publishing.claim import ClaimResult
from app.services.publishing.metrics import METRICS
from app.services.publishing.retry import attempts_exhausted, compute_retry_at

logger = structlog.get_logger(__name__)


class PublishExecutor:
    def __init__(
        self,
        session: AsyncSession,
        *,
        settings: Settings,
        publisher: LinkedInPublisher,
    ) -> None:
        self._db = session
        self._settings = settings
        self._publisher = publisher

    async def mark_submitting(
        self, *, claim: ClaimResult, now: datetime | None = None
    ) -> bool:
        """Durably record that provider submission may begin. Returns False if fenced out."""
        clock = now or datetime.now(UTC)
        post, attempt = await self._lock_owned(claim)
        if post is None or attempt is None:
            return False
        attempt.execution_state = AttemptExecutionState.SUBMITTING.value
        attempt.request_started_at = clock
        attempt.updated_at = clock
        await self._db.commit()
        logger.info(
            "publish.attempt.submitting",
            post_id=str(claim.post.id),
            attempt_id=str(claim.attempt.id),
            fencing_token=str(claim.attempt.fencing_token),
        )
        return True

    async def release_authorization_block(
        self,
        *,
        claim: ClaimResult,
        error_code: str,
        error_category: str,
        now: datetime | None = None,
    ) -> str:
        """Undo a claim for an unauthorized post without failed/published.

        The attempt is recorded as a non-submission safety skip; the post returns to
        ``scheduled`` with a deferred ``next_attempt_at`` so it is not re-dispatched
        immediately. No LinkedIn HTTP call is made.
        """
        clock = now or datetime.now(UTC)
        post, attempt = await self._lock_owned(claim)
        if post is None or attempt is None:
            return "fenced_out"

        attempt.execution_state = AttemptExecutionState.RETRYABLE_FAILURE.value
        attempt.finished_at = clock
        attempt.error_category = error_category
        attempt.sanitized_error_code = error_code
        attempt.next_retry_at = clock + timedelta(seconds=APPROVAL_DEFER_SECONDS)
        attempt.updated_at = clock

        post.status = PostStatus.SCHEDULED.value
        post.next_attempt_at = attempt.next_retry_at
        post.current_attempt_id = None
        post.processing_lease_until = None
        post.dispatch_lease_until = None
        # Do not set last_error_code to a failure that implies LinkedIn rejection.
        post.updated_at = clock
        post.version += 1
        await self._db.commit()
        logger.info(
            "publish.authorization.released_claim",
            post_id=str(post.id),
            attempt_id=str(attempt.id),
            error_code=error_code,
            next_attempt_at=post.next_attempt_at.isoformat() if post.next_attempt_at else None,
        )
        return error_code

    async def release_canary_block(
        self, *, claim: ClaimResult, now: datetime | None = None
    ) -> str:
        """Undo a claim for an unapproved canary post without failed/published."""
        return await self.release_authorization_block(
            claim=claim,
            error_code="live_publish_canary_blocked",
            error_category="canary",
            now=now,
        )

    def invoke_publisher(self, *, claim: ClaimResult) -> PublishOutcome:
        """Call the publisher outside any DB transaction."""
        ctx = PublishExecutionContext(
            post_id=str(claim.post.id),
            attempt_id=str(claim.attempt.id),
            fencing_token=str(claim.attempt.fencing_token),
            attempt_number=claim.attempt.attempt_number,
            worker_id=claim.attempt.worker_id or "unknown",
            celery_task_id=claim.attempt.celery_task_id,
        )
        started = time.perf_counter()
        outcome = self._publisher.publish_text_post(
            connection=claim.connection,
            content=claim.post.content,
            execution_context=ctx,
        )
        METRICS.observe_publish_latency_ms((time.perf_counter() - started) * 1000.0)
        return outcome

    async def apply_outcome(
        self,
        *,
        claim: ClaimResult,
        outcome: PublishOutcome,
        now: datetime | None = None,
    ) -> str:
        """Persist outcome if fencing token still matches. Returns resulting post status."""
        clock = now or datetime.now(UTC)
        post, attempt = await self._lock_owned(claim)
        if post is None or attempt is None:
            logger.info(
                "publish.attempt.stale_fenced",
                post_id=str(claim.post.id),
                attempt_id=str(claim.attempt.id),
                fencing_token=str(claim.attempt.fencing_token),
            )
            return "fenced_out"

        if outcome.kind == OutcomeKind.SUCCESS:
            return await self._apply_success(post, attempt, outcome, clock=clock)
        if outcome.kind in {OutcomeKind.RETRYABLE, OutcomeKind.PRE_NETWORK_FAILURE}:
            return await self._apply_retryable(post, attempt, outcome, clock=clock)
        if outcome.kind in {OutcomeKind.PERMANENT, OutcomeKind.CONNECTION_EXPIRED}:
            if outcome.kind == OutcomeKind.CONNECTION_EXPIRED:
                await self._mark_connection_reauth(claim.connection.id, clock=clock)
            return await self._apply_permanent(post, attempt, outcome, clock=clock)
        # AMBIGUOUS / INTERRUPTED after submission may have started.
        return await self._apply_ambiguous(post, attempt, outcome, clock=clock)

    async def _lock_owned(
        self, claim: ClaimResult
    ) -> tuple[ScheduledPost | None, PublishAttempt | None]:
        dialect = self._db.get_bind().dialect.name
        post_stmt = select(ScheduledPost).where(ScheduledPost.id == claim.post.id)
        if dialect == "postgresql":
            post_stmt = post_stmt.with_for_update()
        post = (await self._db.execute(post_stmt)).scalar_one_or_none()
        if post is None:
            await self._db.commit()
            return None, None
        if post.current_attempt_id != claim.attempt.fencing_token:
            await self._db.commit()
            return None, None
        if post.status != PostStatus.PROCESSING.value:
            await self._db.commit()
            return None, None

        attempt_stmt = select(PublishAttempt).where(PublishAttempt.id == claim.attempt.id)
        if dialect == "postgresql":
            attempt_stmt = attempt_stmt.with_for_update()
        attempt = (await self._db.execute(attempt_stmt)).scalar_one_or_none()
        if attempt is None or attempt.fencing_token != claim.attempt.fencing_token:
            await self._db.commit()
            return None, None
        return post, attempt

    async def _mark_connection_reauth(self, connection_id, *, clock: datetime) -> None:
        result = await self._db.execute(
            select(LinkedInConnection).where(LinkedInConnection.id == connection_id)
        )
        connection = result.scalar_one_or_none()
        if connection is None:
            return
        connection.connection_status = ConnectionStatus.REAUTH_REQUIRED.value
        connection.updated_at = clock

    async def _apply_success(
        self,
        post: ScheduledPost,
        attempt: PublishAttempt,
        outcome: PublishOutcome,
        *,
        clock: datetime,
    ) -> str:
        urn = outcome.provider_post_urn
        # Never persist a simulation URN as a genuine LinkedIn publication.
        if not outcome.simulated and urn and urn.startswith("urn:li:share:fake-"):
            return await self._apply_ambiguous(
                post,
                attempt,
                PublishOutcome(
                    kind=OutcomeKind.AMBIGUOUS,
                    submission_started=True,
                    http_status=outcome.http_status,
                    error_category="provider",
                    sanitized_error_code="rejected_fake_urn_as_real",
                    simulated=False,
                ),
                clock=clock,
            )

        attempt.execution_state = AttemptExecutionState.SUCCEEDED.value
        attempt.finished_at = clock
        attempt.provider_http_status = outcome.http_status
        attempt.provider_post_urn = urn
        attempt.updated_at = clock

        post.status = PostStatus.PUBLISHED.value
        post.published_at = clock
        post.linkedin_post_urn = urn
        post.current_attempt_id = None
        post.processing_lease_until = None
        post.dispatch_lease_until = None
        post.next_attempt_at = None
        post.last_error_code = None
        post.updated_at = clock
        post.version += 1

        if outcome.simulated:
            METRICS.incr("simulated_publications")
        await self._db.commit()
        logger.info(
            "publish.attempt.succeeded",
            post_id=str(post.id),
            attempt_id=str(attempt.id),
            simulated=outcome.simulated,
            provider_post_urn=outcome.provider_post_urn,
        )
        return PostStatus.PUBLISHED.value

    async def _apply_retryable(
        self,
        post: ScheduledPost,
        attempt: PublishAttempt,
        outcome: PublishOutcome,
        *,
        clock: datetime,
    ) -> str:
        if attempts_exhausted(settings=self._settings, attempt_count=post.attempt_count):
            return await self._apply_permanent(
                post,
                attempt,
                PublishOutcome(
                    kind=OutcomeKind.PERMANENT,
                    submission_started=outcome.submission_started,
                    http_status=outcome.http_status,
                    error_category=outcome.error_category or "retry_exhausted",
                    sanitized_error_code="retry_attempts_exhausted",
                    simulated=outcome.simulated,
                ),
                clock=clock,
            )

        next_at = compute_retry_at(
            settings=self._settings,
            attempt_number=post.attempt_count,
            clock=clock,
            retry_after_seconds=outcome.retry_after_seconds,
        )
        attempt.execution_state = AttemptExecutionState.RETRYABLE_FAILURE.value
        attempt.finished_at = clock
        attempt.provider_http_status = outcome.http_status
        attempt.error_category = outcome.error_category
        attempt.sanitized_error_code = outcome.sanitized_error_code
        attempt.next_retry_at = next_at
        attempt.updated_at = clock

        post.status = PostStatus.SCHEDULED.value
        post.next_attempt_at = next_at
        post.current_attempt_id = None
        post.processing_lease_until = None
        post.dispatch_lease_until = None
        post.last_error_code = outcome.sanitized_error_code
        post.last_error_at = clock
        post.updated_at = clock
        post.version += 1

        METRICS.incr("retries_scheduled")
        await self._db.commit()
        logger.info(
            "publish.attempt.retry_scheduled",
            post_id=str(post.id),
            attempt_id=str(attempt.id),
            next_attempt_at=next_at.isoformat(),
            code=outcome.sanitized_error_code,
        )
        return PostStatus.SCHEDULED.value

    async def _apply_permanent(
        self,
        post: ScheduledPost,
        attempt: PublishAttempt,
        outcome: PublishOutcome,
        *,
        clock: datetime,
    ) -> str:
        attempt.execution_state = AttemptExecutionState.PERMANENT_FAILURE.value
        attempt.finished_at = clock
        attempt.provider_http_status = outcome.http_status
        attempt.error_category = outcome.error_category
        attempt.sanitized_error_code = outcome.sanitized_error_code
        attempt.updated_at = clock

        post.status = PostStatus.FAILED.value
        post.current_attempt_id = None
        post.processing_lease_until = None
        post.dispatch_lease_until = None
        post.next_attempt_at = None
        post.last_error_code = outcome.sanitized_error_code
        post.last_error_at = clock
        post.updated_at = clock
        post.version += 1

        METRICS.incr("permanent_failures")
        await self._db.commit()
        logger.info(
            "publish.attempt.permanent_failure",
            post_id=str(post.id),
            attempt_id=str(attempt.id),
            code=outcome.sanitized_error_code,
        )
        return PostStatus.FAILED.value

    async def _apply_ambiguous(
        self,
        post: ScheduledPost,
        attempt: PublishAttempt,
        outcome: PublishOutcome,
        *,
        clock: datetime,
    ) -> str:
        state = (
            AttemptExecutionState.INTERRUPTED.value
            if outcome.kind == OutcomeKind.INTERRUPTED
            else AttemptExecutionState.AMBIGUOUS.value
        )
        attempt.execution_state = state
        attempt.finished_at = clock
        attempt.provider_http_status = outcome.http_status
        attempt.error_category = outcome.error_category
        attempt.sanitized_error_code = outcome.sanitized_error_code
        attempt.updated_at = clock

        post.status = PostStatus.REQUIRES_REVIEW.value
        post.current_attempt_id = None
        post.processing_lease_until = None
        post.dispatch_lease_until = None
        post.next_attempt_at = None
        post.last_error_code = outcome.sanitized_error_code
        post.last_error_at = clock
        post.updated_at = clock
        post.version += 1

        METRICS.incr("uncertain_outcomes")
        await self._db.commit()
        logger.info(
            "publish.attempt.requires_review",
            post_id=str(post.id),
            attempt_id=str(attempt.id),
            code=outcome.sanitized_error_code,
        )
        return PostStatus.REQUIRES_REVIEW.value


async def run_publish_pipeline(
    session: AsyncSession,
    *,
    settings: Settings,
    publisher: LinkedInPublisher,
    post_id: UUID,
    worker_id: str,
    celery_task_id: str | None,
    now: datetime | None = None,
) -> str:
    """Claim → mark submitting → publish → apply. Used by Celery tasks and tests."""
    from app.services.publishing.claim import ClaimService

    clock = now or datetime.now(UTC)

    # Cheap pre-claim canary check (ID allowlist only — avoids loading the row unlocked).
    if not is_post_canary_approved(settings, post_id):
        await defer_unauthorized_post(
            session,
            settings=settings,
            post_id=post_id,
            reason="live_publish_canary_blocked",
            now=clock,
        )
        logger.info(
            "publish.authorization.blocked_before_claim",
            post_id=str(post_id),
            worker_id=worker_id,
            reason="canary_blocked",
        )
        return "canary_blocked"

    claim = await ClaimService(session, settings=settings).claim(
        post_id=post_id,
        worker_id=worker_id,
        celery_task_id=celery_task_id,
        now=clock,
    )
    if claim is None:
        return "skipped"

    executor = PublishExecutor(session, settings=settings, publisher=publisher)

    # Defense in depth: canary + durable DB approval after the row lock.
    if not is_post_canary_approved(settings, claim.post.id):
        await executor.release_canary_block(claim=claim, now=clock)
        return "canary_blocked"
    if db_approval_required(settings) and not is_db_publish_approved(claim.post):
        await executor.release_authorization_block(
            claim=claim,
            error_code="publish_approval_required",
            error_category="approval",
            now=clock,
        )
        return "publish_approval_required"

    marked = await executor.mark_submitting(claim=claim, now=clock)
    if not marked:
        return "fenced_out"

    try:
        outcome = executor.invoke_publisher(claim=claim)
    except Exception:
        logger.exception(
            "publish.attempt.publisher_raised",
            post_id=str(post_id),
            attempt_id=str(claim.attempt.id),
        )
        outcome = PublishOutcome(
            kind=OutcomeKind.AMBIGUOUS,
            submission_started=True,
            error_category="publisher_exception",
            sanitized_error_code="publisher_unhandled_exception",
            simulated=True,
        )

    return await executor.apply_outcome(claim=claim, outcome=outcome, now=clock)
