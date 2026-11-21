"""Database-backed due-post dispatcher with short-lived dispatch leases."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from uuid import UUID

import structlog
from sqlalchemy import and_, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.models import ScheduledPost
from app.models.enums import PostStatus
from app.publishing.authorization import db_approval_required
from app.publishing.canary import canary_enforced
from app.services.publishing.metrics import METRICS

logger = structlog.get_logger(__name__)

EnqueueFn = Callable[[UUID], str | None]

_GATE_ERROR_CODES = (
    "live_publish_canary_blocked",
    "publish_approval_required",
)


class DispatchService:
    def __init__(
        self,
        session: AsyncSession,
        *,
        settings: Settings,
        enqueue: EnqueueFn,
    ) -> None:
        self._db = session
        self._settings = settings
        self._enqueue = enqueue

    async def dispatch_due(self, *, now: datetime | None = None) -> dict[str, int]:
        clock = now or datetime.now(UTC)
        cleared = await self._clear_stale_gate_holds(clock=clock)
        if cleared:
            logger.info("publish.dispatcher.cleared_stale_gate_holds", cleared=cleared)
        claimed_ids = await self._claim_batch(clock=clock)
        METRICS.incr("due_posts_discovered", len(claimed_ids))
        logger.info(
            "publish.dispatcher.scan",
            due_count=len(claimed_ids),
            batch_size=self._settings.dispatch_batch_size,
        )

        queued = 0
        failed = 0
        for post_id in claimed_ids:
            try:
                task_id = self._enqueue(post_id)
                queued += 1
                METRICS.incr("jobs_queued")
                logger.info(
                    "publish.dispatcher.enqueued",
                    post_id=str(post_id),
                    celery_task_id=task_id,
                )
            except Exception:
                failed += 1
                METRICS.incr("queue_failures")
                # Leave the dispatch lease in place; when it expires the post is eligible again.
                logger.exception(
                    "publish.dispatcher.enqueue_failed",
                    post_id=str(post_id),
                )

        return {"claimed": len(claimed_ids), "queued": queued, "failed": failed}

    async def _clear_stale_gate_holds(self, *, clock: datetime) -> int:
        """Clear leftover canary/approval next_attempt parks once the gate is gone.

        Fingerprint: attempt_count == 0 (classic multi-day park) or last_error_code from
        an authorization release. Genuine provider retries keep attempt_count >= 1 and a
        non-gate error code, so they are left alone.
        """
        if canary_enforced(self._settings):
            return 0

        # Only clear rows tagged with authorization-gate error codes.
        # Bare attempt_count==0 matched unrelated holds and raced with shared-DB
        # dispatchers during integration tests against a live worker.
        result = await self._db.execute(
            update(ScheduledPost)
            .where(
                ScheduledPost.status == PostStatus.SCHEDULED.value,
                ScheduledPost.next_attempt_at.is_not(None),
                ScheduledPost.next_attempt_at > clock,
                ScheduledPost.last_error_code.in_(_GATE_ERROR_CODES),
            )
            .values(next_attempt_at=None, dispatch_lease_until=None, updated_at=func.now())
        )
        await self._db.commit()
        return int(result.rowcount or 0)

    async def _claim_batch(self, *, clock: datetime) -> list[UUID]:
        """Lock due scheduled posts, set a short dispatch lease, commit, return IDs.

        Uses FOR UPDATE SKIP LOCKED so concurrent dispatchers do not double-claim.
        Posts are NOT moved to processing here — only leased for queue delivery.
        Multiple due posts (same timestamp or different) are claimed in batch order.
        """
        lease_until = clock + timedelta(seconds=self._settings.dispatch_lease_seconds)
        dialect = self._db.get_bind().dialect.name

        filters = [
            ScheduledPost.status == PostStatus.SCHEDULED.value,
            ScheduledPost.scheduled_at <= clock,
            or_(
                ScheduledPost.next_attempt_at.is_(None),
                ScheduledPost.next_attempt_at <= clock,
            ),
            or_(
                ScheduledPost.dispatch_lease_until.is_(None),
                ScheduledPost.dispatch_lease_until <= clock,
            ),
        ]

        # Real LinkedIn: only lease posts with durable DB approval (hash rechecked later).
        if db_approval_required(self._settings):
            filters.append(ScheduledPost.publish_approved_at.is_not(None))
            filters.append(ScheduledPost.approval_revoked_at.is_(None))
            filters.append(ScheduledPost.publish_approved_by.is_not(None))
            filters.append(ScheduledPost.approved_content_hash.is_not(None))

        # Phase 4C: with real LinkedIn + canary required, never lease unrelated posts.
        if canary_enforced(self._settings):
            approved = self._settings.live_publish_canary_post_ids
            if not approved:
                logger.info(
                    "publish.dispatcher.canary_empty",
                    message="No LIVE_PUBLISH_CANARY_POST_IDS; skipping dispatch.",
                )
                await self._db.commit()
                return []
            filters.append(ScheduledPost.id.in_(approved))

        if dialect == "postgresql":
            stmt = (
                select(ScheduledPost.id)
                .where(and_(*filters))
                .order_by(ScheduledPost.scheduled_at.asc(), ScheduledPost.id.asc())
                .limit(self._settings.dispatch_batch_size)
                .with_for_update(skip_locked=True)
            )
        else:
            # SQLite unit tests: no SKIP LOCKED; still safe under a single dispatcher.
            stmt = (
                select(ScheduledPost.id)
                .where(and_(*filters))
                .order_by(ScheduledPost.scheduled_at.asc(), ScheduledPost.id.asc())
                .limit(self._settings.dispatch_batch_size)
            )

        result = await self._db.execute(stmt)
        ids = list(result.scalars().all())
        if not ids:
            await self._db.commit()
            return []

        await self._db.execute(
            update(ScheduledPost)
            .where(ScheduledPost.id.in_(ids))
            .values(dispatch_lease_until=lease_until, updated_at=func.now())
        )
        # Commit the lease before any Redis I/O so a crash after enqueue still has DB truth.
        await self._db.commit()
        return ids
