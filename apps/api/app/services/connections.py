"""LinkedIn connection status and local disconnect."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import LinkedInConnection, User
from app.models.enums import ConnectionStatus
from app.schemas.auth import LinkedInConnectionResponse, UserProfileResponse


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
        return LinkedInConnectionResponse(
            connected=not reauth and connection.encrypted_access_token is not None,
            connection_status=status,
            id=connection.id,
            display_name=user.display_name,
            avatar_url=user.avatar_url,
            granted_scopes=scopes,
            token_expires_at=connection.token_expires_at,
            reauthorization_required=reauth,
        )

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
        )
