"""Live-publishing canary allowlist helpers (Phase 4C).

When ``PUBLISH_PROVIDER=linkedin`` and ``LIVE_PUBLISH_REQUIRE_CANARY=true`` (default),
only explicitly approved post IDs may be submitted to LinkedIn. Fake-provider mode is
unaffected.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.models import ScheduledPost
from app.models.enums import PostStatus
from app.publishing.gates import AUTH_GATE_RECHECK_SECONDS

logger = structlog.get_logger(__name__)

# Back-compat alias — canary holds use the short gate recheck, not a multi-day park.
CANARY_DEFER_SECONDS = AUTH_GATE_RECHECK_SECONDS


def canary_enforced(settings: Settings) -> bool:
    """True when the real LinkedIn publisher must honor the canary allowlist."""
    return settings.publish_provider == "linkedin" and settings.live_publish_require_canary


def is_post_canary_approved(settings: Settings, post_id: UUID) -> bool:
    """Return whether ``post_id`` may be submitted to LinkedIn under current settings."""
    if not canary_enforced(settings):
        return True
    return post_id in settings.live_publish_canary_post_ids


async def defer_unapproved_post(
    session: AsyncSession,
    *,
    settings: Settings,
    post_id: UUID,
    now: datetime | None = None,
) -> bool:
    """Push an unapproved scheduled post out of the immediate dispatch window.

    Leaves status as ``scheduled`` (not failed/published). Returns True when deferred.
    """
    clock = now or datetime.now(UTC)
    result = await session.execute(select(ScheduledPost).where(ScheduledPost.id == post_id))
    post = result.scalar_one_or_none()
    if post is None or post.status != PostStatus.SCHEDULED.value:
        await session.commit()
        return False

    # Short recheck only — do not park for days after the gate is removed.
    post.next_attempt_at = clock + timedelta(seconds=AUTH_GATE_RECHECK_SECONDS)
    post.dispatch_lease_until = None
    post.updated_at = clock
    await session.commit()
    logger.info(
        "publish.canary.deferred",
        post_id=str(post_id),
        next_attempt_at=post.next_attempt_at.isoformat(),
        recheck_seconds=AUTH_GATE_RECHECK_SECONDS,
        canary_count=len(settings.live_publish_canary_post_ids),
    )
    return True
