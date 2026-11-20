"""LinkedIn OAuth authorization and callback orchestration."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from urllib.parse import urlencode
from uuid import uuid4

import structlog
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import REQUIRED_LINKEDIN_SCOPES, Settings
from app.core.errors import ConflictError, OAuthError
from app.core.security import TokenEncryptor, generate_opaque_token, hash_token
from app.integrations.linkedin import (
    LinkedInClient,
    LinkedInIntegrationError,
    LinkedInOidcValidator,
)
from app.models import LinkedInConnection, OAuthState, User
from app.models.enums import ConnectionStatus
from app.services.sessions import IssuedSession, SessionService

logger = structlog.get_logger(__name__)


@dataclass(frozen=True, slots=True)
class OAuthStart:
    authorization_url: str
    state: str
    browser_nonce: str


@dataclass(frozen=True, slots=True)
class OAuthResult:
    user: User
    issued_session: IssuedSession


class OAuthService:
    def __init__(
        self,
        session: AsyncSession,
        *,
        settings: Settings,
        linkedin: LinkedInClient,
        oidc: LinkedInOidcValidator,
        encryptor: TokenEncryptor,
    ) -> None:
        self._db = session
        self._settings = settings
        self._linkedin = linkedin
        self._oidc = oidc
        self._encryptor = encryptor
        self._sessions = SessionService(session, ttl_seconds=settings.session_ttl_seconds)

    async def start(
        self,
        *,
        existing_session_token: str | None,
    ) -> OAuthStart:
        state = generate_opaque_token()
        browser_nonce = generate_opaque_token()
        now = datetime.now(UTC)
        existing_hash = hash_token(existing_session_token) if existing_session_token else None
        self._db.add(
            OAuthState(
                id=uuid4(),
                state_hash=hash_token(state),
                browser_nonce_hash=hash_token(browser_nonce),
                existing_session_hash=existing_hash,
                expires_at=now + timedelta(seconds=self._settings.oauth_state_ttl_seconds),
                consumed_at=None,
                created_at=now,
            )
        )
        await self._db.commit()
        return OAuthStart(
            authorization_url=self._linkedin.build_authorization_url(state=state),
            state=state,
            browser_nonce=browser_nonce,
        )

    async def complete(
        self,
        *,
        code: str | None,
        state: str | None,
        browser_nonce: str | None,
        error: str | None,
        error_description: str | None,
        current_session_token: str | None,
    ) -> OAuthResult:
        if error:
            raise OAuthError(_provider_error_message(error, error_description))
        if not code or not state or not browser_nonce:
            raise OAuthError("LinkedIn callback was missing required parameters.")

        oauth_state = await self._consume_state(state=state, browser_nonce=browser_nonce)

        try:
            token_response = await self._linkedin.exchange_code(code=code)
            id_claims = self._oidc.validate_id_token(token_response.id_token)
            userinfo = await self._linkedin.fetch_userinfo(access_token=token_response.access_token)
        except LinkedInIntegrationError as exc:
            raise OAuthError(exc.message) from exc

        if userinfo.sub != id_claims.subject:
            raise OAuthError("LinkedIn userinfo subject did not match the ID token subject.")

        granted = set(token_response.scope.split())
        missing = sorted(REQUIRED_LINKEDIN_SCOPES - granted)
        if missing:
            raise OAuthError(
                "LinkedIn did not grant the required scopes: "
                f"{', '.join(missing)}. Enable the corresponding products on the "
                "LinkedIn developer app and try again."
            )

        current_user = await self._resolve_reconnect_user(
            oauth_state=oauth_state,
            current_session_token=current_session_token,
        )
        if current_user is not None and current_user.linkedin_subject != id_claims.subject:
            raise ConflictError(
                "This LinkedIn account does not match the signed-in PostPilot user. "
                "Sign out first, or reconnect the same LinkedIn identity."
            )

        user = await self._upsert_user(
            subject=id_claims.subject,
            display_name=userinfo.name,
            email=userinfo.email,
            avatar_url=userinfo.picture,
        )
        await self._upsert_connection(
            user=user,
            provider_subject=id_claims.subject,
            access_token=token_response.access_token,
            expires_in=token_response.expires_in,
            granted_scopes=token_response.scope,
        )

        issued = await self._sessions.rotate_session(
            user_id=user.id,
            previous_token=current_session_token,
        )
        await self._db.commit()
        await self._db.refresh(user)
        logger.info("oauth.completed", user_id=str(user.id))
        return OAuthResult(user=user, issued_session=issued)

    async def _consume_state(self, *, state: str, browser_nonce: str) -> OAuthState:
        now = datetime.now(UTC)
        result = await self._db.execute(
            update(OAuthState)
            .where(
                OAuthState.state_hash == hash_token(state),
                OAuthState.consumed_at.is_(None),
            )
            .values(consumed_at=now)
            .returning(OAuthState)
        )
        row = result.scalar_one_or_none()
        if row is None:
            raise OAuthError("OAuth state is invalid, expired, or already used.")
        expires_at = row.expires_at
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=UTC)
        if expires_at <= now:
            raise OAuthError("OAuth state is invalid, expired, or already used.")
        if row.browser_nonce_hash != hash_token(browser_nonce):
            raise OAuthError("OAuth browser nonce did not match.")
        await self._db.commit()
        return row

    async def _resolve_reconnect_user(
        self,
        *,
        oauth_state: OAuthState,
        current_session_token: str | None,
    ) -> User | None:
        token = current_session_token
        if token is None:
            return None
        user = await self._sessions.get_user_for_token(token)
        if user is None:
            return None
        # If the start step recorded a session hash, require it still matches.
        if (
            oauth_state.existing_session_hash is not None
            and hash_token(token) != oauth_state.existing_session_hash
        ):
            raise OAuthError("OAuth session binding no longer matches.")
        return user

    async def _upsert_user(
        self,
        *,
        subject: str,
        display_name: str,
        email: str | None,
        avatar_url: str | None,
    ) -> User:
        result = await self._db.execute(select(User).where(User.linkedin_subject == subject))
        user = result.scalar_one_or_none()
        now = datetime.now(UTC)
        if user is None:
            user = User(
                id=uuid4(),
                linkedin_subject=subject,
                display_name=display_name,
                email=email,
                avatar_url=avatar_url,
                created_at=now,
                updated_at=now,
            )
            self._db.add(user)
        else:
            user.display_name = display_name
            user.email = email
            user.avatar_url = avatar_url
            user.updated_at = now
        await self._db.flush()
        return user

    async def _upsert_connection(
        self,
        *,
        user: User,
        provider_subject: str,
        access_token: str,
        expires_in: int,
        granted_scopes: str,
    ) -> LinkedInConnection:
        result = await self._db.execute(
            select(LinkedInConnection).where(LinkedInConnection.user_id == user.id)
        )
        connection = result.scalar_one_or_none()
        now = datetime.now(UTC)
        encrypted = self._encryptor.encrypt(access_token)
        expires_at = now + timedelta(seconds=expires_in)
        if connection is None:
            connection = LinkedInConnection(
                id=uuid4(),
                user_id=user.id,
                provider_subject=provider_subject,
                encrypted_access_token=encrypted,
                token_expires_at=expires_at,
                granted_scopes=granted_scopes,
                connection_status=ConnectionStatus.CONNECTED.value,
                created_at=now,
                updated_at=now,
            )
            self._db.add(connection)
        else:
            if connection.provider_subject != provider_subject:
                raise ConflictError(
                    "Stored LinkedIn identity does not match the authenticated subject."
                )
            connection.encrypted_access_token = encrypted
            connection.token_expires_at = expires_at
            connection.granted_scopes = granted_scopes
            connection.connection_status = ConnectionStatus.CONNECTED.value
            connection.updated_at = now
        await self._db.flush()
        return connection


def frontend_redirect(web_base_url: str, *, path: str, params: dict[str, str]) -> str:
    query = urlencode(params)
    return f"{web_base_url}{path}?{query}"


def _provider_error_message(error: str, description: str | None) -> str:
    if error == "user_cancelled_login" or error == "user_cancelled_authorize":
        return "LinkedIn authorization was cancelled."
    if error == "access_denied":
        return "LinkedIn authorization was denied."
    if description:
        # Descriptions are user-facing provider text; still avoid logging secrets.
        return f"LinkedIn authorization failed: {error}."
    return f"LinkedIn authorization failed: {error}."
