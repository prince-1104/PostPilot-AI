"""Read-only diagnostics for live LinkedIn publishing readiness (Phase 4C)."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.models import LinkedInConnection, ScheduledPost, User
from app.models.enums import ConnectionStatus, PostStatus
from app.publishing.canary import canary_enforced, is_post_canary_approved
from app.publishing.person_urn import PersonUrnError, person_urn_from_oidc_subject
from app.schemas.publishing_readiness import PublishingReadinessResponse, ReadinessCheck

POSTING_SCOPE = "w_member_social"


class PublishingReadinessService:
    def __init__(self, session: AsyncSession, *, settings: Settings) -> None:
        self._db = session
        self._settings = settings

    async def diagnose(
        self, user: User, *, post_id: UUID | None = None
    ) -> PublishingReadinessResponse:
        connection = (
            await self._db.execute(
                select(LinkedInConnection).where(LinkedInConnection.user_id == user.id)
            )
        ).scalar_one_or_none()

        checks: list[ReadinessCheck] = []
        now = datetime.now(UTC)

        connected = (
            connection is not None
            and connection.connection_status == ConnectionStatus.CONNECTED.value
            and bool(connection.encrypted_access_token)
        )
        checks.append(
            ReadinessCheck(
                key="linkedin_connected",
                ok=connected,
                detail=(
                    "LinkedIn connection is active with a stored access token."
                    if connected
                    else "Connect or reconnect LinkedIn on /connections."
                ),
            )
        )

        scopes = (
            [part for part in connection.granted_scopes.replace(",", " ").split() if part]
            if connection and connection.granted_scopes
            else []
        )
        has_scope = POSTING_SCOPE in scopes
        checks.append(
            ReadinessCheck(
                key="w_member_social",
                ok=has_scope,
                detail=(
                    "Publishing scope w_member_social is present."
                    if has_scope
                    else "Reconnect LinkedIn and grant w_member_social."
                ),
            )
        )

        token_unexpired = False
        if connection and connection.token_expires_at is not None:
            expires = connection.token_expires_at
            if expires.tzinfo is None:
                expires = expires.replace(tzinfo=UTC)
            token_unexpired = expires > now
        checks.append(
            ReadinessCheck(
                key="token_unexpired",
                ok=token_unexpired,
                detail=(
                    "Access token is not expired."
                    if token_unexpired
                    else "Access token missing or expired; reconnect (no refresh tokens)."
                ),
            )
        )

        person_urn: str | None = None
        oidc_ok = False
        if connection and connection.provider_subject:
            try:
                person_urn = person_urn_from_oidc_subject(connection.provider_subject)
                oidc_ok = True
            except PersonUrnError:
                oidc_ok = False
        checks.append(
            ReadinessCheck(
                key="oidc_person_urn",
                ok=oidc_ok,
                detail=(
                    f"Person URN ready ({person_urn})."
                    if oidc_ok and person_urn
                    else "OIDC subject missing or cannot form urn:li:person:…"
                ),
            )
        )

        api_version_ok = (
            self._settings.linkedin_api_version.isdigit()
            and len(self._settings.linkedin_api_version) == 6
        )
        checks.append(
            ReadinessCheck(
                key="linkedin_api_version",
                ok=api_version_ok,
                detail=f"LINKEDIN_API_VERSION={self._settings.linkedin_api_version}",
            )
        )

        provider_linkedin = self._settings.publish_provider == "linkedin"
        checks.append(
            ReadinessCheck(
                key="publish_provider_linkedin",
                ok=provider_linkedin,
                detail=(
                    "PUBLISH_PROVIDER=linkedin"
                    if provider_linkedin
                    else (
                        f"PUBLISH_PROVIDER={self._settings.publish_provider} "
                        "(fake is safe default)"
                    )
                ),
            )
        )

        real_enabled = self._settings.enable_real_publishing
        checks.append(
            ReadinessCheck(
                key="enable_real_publishing",
                ok=real_enabled,
                detail=(
                    "ENABLE_REAL_PUBLISHING=true"
                    if real_enabled
                    else "ENABLE_REAL_PUBLISHING=false (live publishing disabled)"
                ),
            )
        )

        require_canary = self._settings.live_publish_require_canary
        checks.append(
            ReadinessCheck(
                key="canary_gate",
                ok=True,
                detail=(
                    "LIVE_PUBLISH_REQUIRE_CANARY=true — only allowlisted post IDs may publish."
                    if require_canary
                    else "LIVE_PUBLISH_REQUIRE_CANARY=false — canary gate disabled (use with care)."
                ),
            )
        )

        selected_status: str | None = None
        selected_approved: bool | None = None
        if post_id is not None:
            post = (
                await self._db.execute(
                    select(ScheduledPost).where(
                        ScheduledPost.id == post_id,
                        ScheduledPost.user_id == user.id,
                    )
                )
            ).scalar_one_or_none()
            if post is None:
                selected_approved = False
                checks.append(
                    ReadinessCheck(
                        key="selected_post",
                        ok=False,
                        detail="Selected post was not found for this user.",
                    )
                )
            else:
                selected_status = post.status
                selected_approved = is_post_canary_approved(self._settings, post.id)
                checks.append(
                    ReadinessCheck(
                        key="selected_post_canary",
                        ok=selected_approved if canary_enforced(self._settings) else True,
                        detail=(
                            "Post ID is on LIVE_PUBLISH_CANARY_POST_IDS."
                            if selected_approved
                            else "Post ID is NOT approved for live publishing."
                        ),
                    )
                )

        pending = await self._count_pending(user.id)
        pending_non_canary = await self._count_pending_non_canary(user.id)

        publishing_verified = await self._has_real_published(user.id)

        configured = connected and has_scope and oidc_ok and api_version_ok
        ready_for_test = (
            configured
            and token_unexpired
            and provider_linkedin
            and real_enabled
            and (
                not canary_enforced(self._settings)
                or (
                    post_id is not None
                    and selected_approved is True
                )
            )
        )

        return PublishingReadinessResponse(
            configured=configured,
            ready_for_test=ready_for_test,
            publishing_verified=publishing_verified,
            publish_provider=self._settings.publish_provider,
            enable_real_publishing=real_enabled,
            live_publish_require_canary=require_canary,
            canary_post_ids=list(self._settings.live_publish_canary_post_ids),
            linkedin_api_version=self._settings.linkedin_api_version,
            person_urn=person_urn if connected else None,
            selected_post_id=post_id,
            selected_post_canary_approved=selected_approved,
            selected_post_status=selected_status,
            pending_scheduled_posts=pending,
            pending_scheduled_non_canary=pending_non_canary,
            checks=checks,
        )

    async def _count_pending(self, user_id: UUID) -> int:
        result = await self._db.execute(
            select(func.count())
            .select_from(ScheduledPost)
            .where(
                ScheduledPost.user_id == user_id,
                ScheduledPost.status == PostStatus.SCHEDULED.value,
            )
        )
        return int(result.scalar_one())

    async def _count_pending_non_canary(self, user_id: UUID) -> int:
        if not canary_enforced(self._settings):
            return 0
        approved = self._settings.live_publish_canary_post_ids
        stmt = (
            select(func.count())
            .select_from(ScheduledPost)
            .where(
                ScheduledPost.user_id == user_id,
                ScheduledPost.status == PostStatus.SCHEDULED.value,
            )
        )
        if approved:
            stmt = stmt.where(ScheduledPost.id.not_in(approved))
        result = await self._db.execute(stmt)
        return int(result.scalar_one())

    async def _has_real_published(self, user_id: UUID) -> bool:
        from sqlalchemy import not_

        result = await self._db.execute(
            select(ScheduledPost.id)
            .where(
                ScheduledPost.user_id == user_id,
                ScheduledPost.status == PostStatus.PUBLISHED.value,
                ScheduledPost.linkedin_post_urn.is_not(None),
                not_(ScheduledPost.linkedin_post_urn.like("urn:li:share:fake-%")),
            )
            .limit(1)
        )
        return result.scalar_one_or_none() is not None
