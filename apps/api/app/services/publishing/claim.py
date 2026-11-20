"""Atomic worker claim: scheduled -> processing + publish_attempt row."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.models import LinkedInConnection, PublishAttempt, ScheduledPost
from app.models.enums import AttemptExecutionState, ConnectionStatus, PostStatus
from app.services.publishing.metrics import METRICS

logger = structlog.get_logger(__name__)

POSTING_SCOPE = "w_member_social"


@dataclass(frozen=True, slots=True)
class ClaimResult:
    post: ScheduledPost
    attempt: PublishAttempt
    connection: LinkedInConnection
    skipped_reason: str | None = None


class ClaimService:
    def __init__(self, session: AsyncSession, *, settings: Settings) -> None:
        self._db = session
        self._settings = settings

    async def claim(
        self,
        *,
        post_id: UUID,
        worker_id: str,
        celery_task_id: str | None,
        now: datetime | None = None,
    ) -> ClaimResult | None:
        """Lock, validate, transition to processing, create attempt, commit.

        Returns None when the post must be skipped (cancelled, not due, etc.).
        """
        clock = now or datetime.now(UTC)
        dialect = self._db.get_bind().dialect.name

        stmt = select(ScheduledPost).where(ScheduledPost.id == post_id)
        if dialect == "postgresql":
            stmt = stmt.with_for_update()
        result = await self._db.execute(stmt)
        post = result.scalar_one_or_none()
        if post is None:
            METRICS.incr("claims_skipped")
            logger.info("publish.claim.missing", post_id=str(post_id))
            await self._db.commit()
            return None

        if post.status != PostStatus.SCHEDULED.value:
            METRICS.incr("claims_skipped")
            logger.info(
                "publish.claim.skip_status",
                post_id=str(post_id),
                status=post.status,
            )
            await self._db.commit()
            return None

        if post.scheduled_at.astimezone(UTC) > clock:
            METRICS.incr("claims_skipped")
            logger.info("publish.claim.skip_not_due", post_id=str(post_id))
            await self._db.commit()
            return None

        if post.next_attempt_at is not None and post.next_attempt_at.astimezone(UTC) > clock:
            METRICS.incr("claims_skipped")
            logger.info("publish.claim.skip_backoff", post_id=str(post_id))
            await self._db.commit()
            return None

        connection = await self._load_connection(post.linkedin_connection_id)
        if connection is None or connection.user_id != post.user_id:
            await self._fail_permanent(
                post,
                clock=clock,
                code="connection_missing",
                worker_id=worker_id,
                celery_task_id=celery_task_id,
            )
            return None
        if not self._connection_eligible(connection, clock=clock):
            await self._fail_permanent(
                post,
                clock=clock,
                code="connection_not_eligible",
                worker_id=worker_id,
                celery_task_id=celery_task_id,
            )
            return None

        attempt_number = post.attempt_count + 1
        fencing_token = uuid4()
        attempt_id = uuid4()
        lease_until = clock + timedelta(seconds=self._settings.processing_lease_seconds)

        attempt = PublishAttempt(
            id=attempt_id,
            post_id=post.id,
            attempt_number=attempt_number,
            fencing_token=fencing_token,
            execution_state=AttemptExecutionState.CLAIMED.value,
            started_at=clock,
            worker_id=worker_id,
            celery_task_id=celery_task_id,
            created_at=clock,
            updated_at=clock,
        )
        self._db.add(attempt)

        post.status = PostStatus.PROCESSING.value
        post.attempt_count = attempt_number
        post.current_attempt_id = fencing_token
        post.processing_lease_until = lease_until
        post.dispatch_lease_until = None
        post.updated_at = clock
        post.version += 1

        delay_ms = max(
            0.0,
            (clock - post.scheduled_at.astimezone(UTC)).total_seconds() * 1000.0,
        )
        METRICS.observe_scheduling_delay_ms(delay_ms)
        METRICS.incr("claims_succeeded")

        await self._db.commit()
        await self._db.refresh(post)
        await self._db.refresh(attempt)
        await self._db.refresh(connection)

        logger.info(
            "publish.claim.acquired",
            post_id=str(post.id),
            attempt_id=str(attempt.id),
            fencing_token=str(fencing_token),
            attempt_number=attempt_number,
            worker_id=worker_id,
        )
        return ClaimResult(post=post, attempt=attempt, connection=connection)

    async def _load_connection(self, connection_id: UUID) -> LinkedInConnection | None:
        result = await self._db.execute(
            select(LinkedInConnection).where(LinkedInConnection.id == connection_id)
        )
        return result.scalar_one_or_none()

    def _connection_eligible(self, connection: LinkedInConnection, *, clock: datetime) -> bool:
        if connection.connection_status != ConnectionStatus.CONNECTED.value:
            return False
        if not connection.encrypted_access_token:
            return False
        scopes = {part for part in connection.granted_scopes.replace(",", " ").split() if part}
        if POSTING_SCOPE not in scopes:
            return False
        if connection.token_expires_at is not None:
            expires = connection.token_expires_at
            if expires.tzinfo is None:
                expires = expires.replace(tzinfo=UTC)
            if expires <= clock:
                return False
        return True

    async def _fail_permanent(
        self,
        post: ScheduledPost,
        *,
        clock: datetime,
        code: str,
        worker_id: str,
        celery_task_id: str | None,
    ) -> None:
        attempt_number = post.attempt_count + 1
        fencing = uuid4()
        attempt = PublishAttempt(
            id=uuid4(),
            post_id=post.id,
            attempt_number=attempt_number,
            fencing_token=fencing,
            execution_state=AttemptExecutionState.PERMANENT_FAILURE.value,
            started_at=clock,
            finished_at=clock,
            error_category="connection",
            sanitized_error_code=code,
            worker_id=worker_id,
            celery_task_id=celery_task_id,
            created_at=clock,
            updated_at=clock,
        )
        self._db.add(attempt)
        post.status = PostStatus.FAILED.value
        post.attempt_count = attempt_number
        post.current_attempt_id = None
        post.processing_lease_until = None
        post.dispatch_lease_until = None
        post.last_error_code = code
        post.last_error_at = clock
        post.updated_at = clock
        post.version += 1
        METRICS.incr("permanent_failures")
        await self._db.commit()
        logger.info(
            "publish.claim.permanent_connection_failure",
            post_id=str(post.id),
            code=code,
        )
