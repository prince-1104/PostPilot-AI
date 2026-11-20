"""LinkedIn connection status and local disconnect."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import not_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import LinkedInConnection, ScheduledPost, User
from app.models.enums import ConnectionStatus, PostStatus
from app.publishing.person_urn import PersonUrnError, person_urn_from_oidc_subject
from app.schemas.auth import LinkedInConnectionResponse, UserProfileResponse

POSTING_SCOPE = "w_member_social"


def user_to_profile(user: User) -> UserProfileResponse:
    return UserProfileResponse(
        id=user.id,
        display_name=user.display_name,
        email=user.email,
        avatar_url=user.avatar_url,
        linkedin_subject=user.linkedin_subject,
    )


class ConnectionService:
    def __init__(self, session: AsyncSession) -> None:
        self._db = session

    async def get_linkedin_status(self, user: User) -> LinkedInConnectionResponse:
        result = await self._db.execute(
            select(LinkedInConnection).where(LinkedInConnection.user_id == user.id)
        )
        connection = result.scalar_one_or_none()
        if connection is None:
            return LinkedInConnectionResponse(
                connected=False,
                connection_status=ConnectionStatus.DISCONNECTED.value,
                reauthorization_required=False,
            )
        if connection.connection_status == ConnectionStatus.DISCONNECTED:
            return LinkedInConnectionResponse(
                connected=False,
                connection_status=ConnectionStatus.DISCONNECTED.value,
                id=connection.id,
                display_name=user.display_name,
                avatar_url=user.avatar_url,
                reauthorization_required=False,
            )

        now = datetime.now(UTC)
        expires_at = connection.token_expires_at
        if expires_at is not None and expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=UTC)
        expired = (
            expires_at is not None and expires_at <= now
        ) or connection.encrypted_access_token is None
        reauth = expired or connection.connection_status == ConnectionStatus.REAUTH_REQUIRED
        status = ConnectionStatus.REAUTH_REQUIRED.value if reauth else connection.connection_status
        scopes = [part for part in connection.granted_scopes.split() if part]
        has_publish = POSTING_SCOPE in scopes
        token_unexpired = not expired
        connected = not reauth and connection.encrypted_access_token is not None
        person_urn: str | None = None
        try:
            person_urn = person_urn_from_oidc_subject(connection.provider_subject)
        except PersonUrnError:
            person_urn = None

        publishing_verified = await self._has_real_published_post(user.id)

        return LinkedInConnectionResponse(
            connected=connected,
            connection_status=status,
            id=connection.id,
            display_name=user.display_name,
            avatar_url=user.avatar_url,
            granted_scopes=scopes,
            token_expires_at=connection.token_expires_at,
            reauthorization_required=reauth,
            has_publishing_permission=has_publish,
            token_unexpired=token_unexpired,
            ready_to_schedule=(
                connected and has_publish and token_unexpired and person_urn is not None
            ),
            publishing_verified=publishing_verified,
            person_urn=person_urn if connected else None,
        )

    async def _has_real_published_post(self, user_id) -> bool:
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

    async def disconnect_linkedin(self, user: User) -> LinkedInConnectionResponse:
        """Invalidate locally stored LinkedIn credentials without deleting the user.

        LinkedIn does not offer a standard revoke for these member tokens in this
        flow, so disconnection is local only.
        """
        result = await self._db.execute(
            select(LinkedInConnection).where(LinkedInConnection.user_id == user.id)
        )
        connection = result.scalar_one_or_none()
        now = datetime.now(UTC)
        if connection is None:
            self._db.add(
                LinkedInConnection(
                    id=uuid4(),
                    user_id=user.id,
                    provider_subject=user.linkedin_subject,
                    encrypted_access_token=None,
                    token_expires_at=None,
                    granted_scopes="",
                    connection_status=ConnectionStatus.DISCONNECTED.value,
                    created_at=now,
                    updated_at=now,
                )
            )
        else:
            connection.encrypted_access_token = None
            connection.token_expires_at = None
            connection.granted_scopes = ""
            connection.connection_status = ConnectionStatus.DISCONNECTED.value
            connection.updated_at = now
        await self._db.commit()
        result = await self._db.execute(
            select(LinkedInConnection).where(LinkedInConnection.user_id == user.id)
        )
        connection = result.scalar_one_or_none()
        return LinkedInConnectionResponse(
            connected=False,
            connection_status=ConnectionStatus.DISCONNECTED.value,
            id=connection.id if connection is not None else None,
            display_name=user.display_name,
            avatar_url=user.avatar_url,
            granted_scopes=[],
            token_expires_at=None,
            reauthorization_required=False,
            disconnect_is_local_only=True,
            has_publishing_permission=False,
            token_unexpired=False,
            ready_to_schedule=False,
            publishing_verified=False,
            person_urn=None,
        )
