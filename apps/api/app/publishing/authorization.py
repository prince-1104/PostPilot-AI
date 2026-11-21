"""Durable per-post publishing approval checks.

Database approval is required whenever ``PUBLISH_PROVIDER=linkedin``. The temporary
env canary allowlist remains an additional gate when ``LIVE_PUBLISH_REQUIRE_CANARY``
is true. Fake-provider mode skips DB approval so isolated tests keep working.

Approval binds to content + schedule + timezone + connection (not worker OCC version),
so Celery version bumps never silently revoke a valid user approval.
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, timedelta
from uuid import UUID

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.models import ScheduledPost
from app.models.enums import PostStatus
from app.publishing.canary import canary_enforced, is_post_canary_approved
from app.publishing.gates import AUTH_GATE_RECHECK_SECONDS

logger = structlog.get_logger(__name__)

# Back-compat alias — approval holds use the short gate recheck.
APPROVAL_DEFER_SECONDS = AUTH_GATE_RECHECK_SECONDS


def approval_payload_hash(
    *,
    content: str,
    scheduled_at: datetime,
    timezone: str,
    linkedin_connection_id: UUID,
) -> str:
    """Hash of the exact payload the user confirmed for LinkedIn publication."""
    utc = (
        scheduled_at.astimezone(UTC)
        if scheduled_at.tzinfo is not None
        else scheduled_at.replace(tzinfo=UTC)
    )
    normalized = {
        "content": content,
        "scheduled_at": utc.isoformat(),
        "timezone": timezone,
        "linkedin_connection_id": str(linkedin_connection_id),
    }
    payload = json.dumps(normalized, separators=(",", ":"), sort_keys=True)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def db_approval_required(settings: Settings) -> bool:
    """True when real LinkedIn publishing must honor per-post DB approval."""
    return settings.publish_provider == "linkedin"


def is_db_publish_approved(post: ScheduledPost) -> bool:
    """Return whether the post currently carries a valid publishing approval."""
    if post.publish_approved_at is None:
        return False
    if post.approval_revoked_at is not None:
        return False
    if post.publish_approved_by is None:
        return False
    if not post.approved_content_hash:
        return False
    expected = approval_payload_hash(
        content=post.content,
        scheduled_at=post.scheduled_at,
        timezone=post.timezone,
        linkedin_connection_id=post.linkedin_connection_id,
    )
    return post.approved_content_hash == expected


def is_post_authorized_to_publish(settings: Settings, post: ScheduledPost) -> bool:
    """Combined authorization: DB approval (linkedin) + optional env canary."""
    if db_approval_required(settings) and not is_db_publish_approved(post):
        return False
    return is_post_canary_approved(settings, post.id)


def apply_publish_approval(
    post: ScheduledPost,
    *,
    approved_by: UUID,
    clock: datetime,
) -> None:
    """Stamp durable approval for the current payload (session user only)."""
    post.publish_approved_at = clock
    post.publish_approved_by = approved_by
    post.approved_content_hash = approval_payload_hash(
        content=post.content,
        scheduled_at=post.scheduled_at,
        timezone=post.timezone,
        linkedin_connection_id=post.linkedin_connection_id,
    )
    post.approved_version = post.version
    post.approval_revoked_at = None
    # Clear gate holds so the post is eligible as soon as scheduled_at is due.
    post.next_attempt_at = None


def revoke_publish_approval(post: ScheduledPost, *, clock: datetime) -> None:
    """Invalidate publishing authorization (edit without re-confirm, or cancel)."""
    if post.publish_approved_at is not None and post.approval_revoked_at is None:
        post.approval_revoked_at = clock


async def defer_unauthorized_post(
    session: AsyncSession,
    *,
    settings: Settings,
    post_id: UUID,
    reason: str,
    now: datetime | None = None,
) -> bool:
    """Briefly pause an unauthorized post so workers do not busy-loop.

    Does not use multi-day parking. The dispatcher already excludes most unauthorized
    posts; this only covers races (settings/hash changed after lease).
    """
    clock = now or datetime.now(UTC)
    result = await session.execute(select(ScheduledPost).where(ScheduledPost.id == post_id))
    post = result.scalar_one_or_none()
    if post is None or post.status != PostStatus.SCHEDULED.value:
        await session.commit()
        return False

    post.next_attempt_at = clock + timedelta(seconds=AUTH_GATE_RECHECK_SECONDS)
    post.dispatch_lease_until = None
    post.updated_at = clock
    await session.commit()
    logger.info(
        "publish.authorization.deferred",
        post_id=str(post_id),
        reason=reason,
        next_attempt_at=post.next_attempt_at.isoformat(),
        recheck_seconds=AUTH_GATE_RECHECK_SECONDS,
        canary_enforced=canary_enforced(settings),
    )
    return True
