"""LinkedIn OAuth start/callback, state validation, and reconnection."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from urllib.parse import parse_qs, urlparse

import pytest
from fastapi import FastAPI
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.cookies import OAUTH_NONCE_COOKIE, SESSION_COOKIE
from app.core.errors import ConflictError, OAuthError
from app.core.security import TokenEncryptor, hash_token
from app.integrations.linkedin import (
    LinkedInOidcValidator,
    LinkedInTokenExchangeError,
    LinkedInUserInfo,
)
from app.models import LinkedInConnection, OAuthState, User
from app.services.oauth import OAuthService
from tests.conftest import (
    ALLOWED_ORIGIN,
    LINKEDIN_CLIENT_ID,
    LINKEDIN_REDIRECT_URI,
    LINKEDIN_SCOPES,
    StaticJwks,
    seed_user_with_session,
    session_cookie_header,
)
from tests.fakes import FakeLinkedInClient


def _service(
    session: AsyncSession,
    settings,
    *,
    linkedin: FakeLinkedInClient,
    jwks: StaticJwks,
    encryptor: TokenEncryptor,
) -> OAuthService:
    return OAuthService(
        session,
        settings=settings,
        linkedin=linkedin,
        oidc=LinkedInOidcValidator(client_id=LINKEDIN_CLIENT_ID, jwks_client=jwks),
        encryptor=encryptor,
    )


@pytest.mark.asyncio
async def test_authorization_url_construction(
    db_session: AsyncSession,
    settings,
    token_encryptor: TokenEncryptor,
    static_jwks: StaticJwks,
    make_id_token,
) -> None:
    linkedin = FakeLinkedInClient(id_token=make_id_token())
    start = await _service(
        db_session, settings, linkedin=linkedin, jwks=static_jwks, encryptor=token_encryptor
    ).start(existing_session_token=None)

    parsed = urlparse(start.authorization_url)
    query = parse_qs(parsed.query)
    assert parsed.scheme == "https"
    assert parsed.netloc == "www.linkedin.com"
    assert parsed.path == "/oauth/v2/authorization"
    assert query["response_type"] == ["code"]
    assert query["client_id"] == [LINKEDIN_CLIENT_ID]
    assert query["redirect_uri"] == [LINKEDIN_REDIRECT_URI]
    assert query["scope"] == [LINKEDIN_SCOPES]
    assert query["state"] == [start.state]
    assert "client_secret" not in query


@pytest.mark.asyncio
async def test_oauth_start_persists_hashed_state_only(
    db_session: AsyncSession,
    settings,
    token_encryptor: TokenEncryptor,
    static_jwks: StaticJwks,
    make_id_token,
) -> None:
    linkedin = FakeLinkedInClient(id_token=make_id_token())
    start = await _service(
        db_session, settings, linkedin=linkedin, jwks=static_jwks, encryptor=token_encryptor
    ).start(existing_session_token=None)

    rows = (await db_session.execute(select(OAuthState))).scalars().all()
    assert len(rows) == 1
    assert rows[0].state_hash == hash_token(start.state)
    assert rows[0].browser_nonce_hash == hash_token(start.browser_nonce)
    assert start.state not in rows[0].state_hash or len(start.state) != 64


@pytest.mark.asyncio
async def test_state_replay_is_rejected(
    db_session: AsyncSession,
    settings,
    token_encryptor: TokenEncryptor,
    static_jwks: StaticJwks,
    make_id_token,
) -> None:
    id_token = make_id_token()
    linkedin = FakeLinkedInClient(id_token=id_token)
    service = _service(
        db_session, settings, linkedin=linkedin, jwks=static_jwks, encryptor=token_encryptor
    )
    start = await service.start(existing_session_token=None)
    await service.complete(
        code="auth-code",
        state=start.state,
        browser_nonce=start.browser_nonce,
        error=None,
        error_description=None,
        current_session_token=None,
    )
    with pytest.raises(OAuthError, match="invalid, expired, or already used"):
        await service.complete(
            code="auth-code-2",
            state=start.state,
            browser_nonce=start.browser_nonce,
            error=None,
            error_description=None,
            current_session_token=None,
        )


@pytest.mark.asyncio
async def test_expired_state_is_rejected(
    db_session: AsyncSession,
    settings,
    token_encryptor: TokenEncryptor,
    static_jwks: StaticJwks,
    make_id_token,
) -> None:
    linkedin = FakeLinkedInClient(id_token=make_id_token())
    service = _service(
        db_session, settings, linkedin=linkedin, jwks=static_jwks, encryptor=token_encryptor
    )
    start = await service.start(existing_session_token=None)
    row = (await db_session.execute(select(OAuthState))).scalar_one()
    row.expires_at = datetime.now(UTC) - timedelta(seconds=1)
    await db_session.commit()

    with pytest.raises(OAuthError, match="invalid, expired, or already used"):
        await service.complete(
            code="auth-code",
            state=start.state,
            browser_nonce=start.browser_nonce,
            error=None,
            error_description=None,
            current_session_token=None,
        )


@pytest.mark.asyncio
async def test_invalid_browser_nonce_is_rejected(
    db_session: AsyncSession,
    settings,
    token_encryptor: TokenEncryptor,
    static_jwks: StaticJwks,
    make_id_token,
) -> None:
    linkedin = FakeLinkedInClient(id_token=make_id_token())
    service = _service(
        db_session, settings, linkedin=linkedin, jwks=static_jwks, encryptor=token_encryptor
    )
    start = await service.start(existing_session_token=None)
    with pytest.raises(OAuthError, match="browser nonce"):
        await service.complete(
            code="auth-code",
            state=start.state,
            browser_nonce="wrong-nonce",
            error=None,
            error_description=None,
            current_session_token=None,
        )


@pytest.mark.asyncio
async def test_linkedin_authorization_denial(
    db_session: AsyncSession,
    settings,
    token_encryptor: TokenEncryptor,
    static_jwks: StaticJwks,
    make_id_token,
) -> None:
    linkedin = FakeLinkedInClient(id_token=make_id_token())
    service = _service(
        db_session, settings, linkedin=linkedin, jwks=static_jwks, encryptor=token_encryptor
    )
    with pytest.raises(OAuthError, match="denied"):
        await service.complete(
            code=None,
            state=None,
            browser_nonce=None,
            error="access_denied",
            error_description="user denied",
            current_session_token=None,
        )


@pytest.mark.asyncio
async def test_token_exchange_error(
    db_session: AsyncSession,
    settings,
    token_encryptor: TokenEncryptor,
    static_jwks: StaticJwks,
    make_id_token,
) -> None:
    linkedin = FakeLinkedInClient(
        id_token=make_id_token(),
        exchange_error=LinkedInTokenExchangeError(
            "LinkedIn rejected the authorization code exchange."
        ),
    )
    service = _service(
        db_session, settings, linkedin=linkedin, jwks=static_jwks, encryptor=token_encryptor
    )
    start = await service.start(existing_session_token=None)
    with pytest.raises(OAuthError, match="rejected the authorization code"):
        await service.complete(
            code="bad-code",
            state=start.state,
            browser_nonce=start.browser_nonce,
            error=None,
            error_description=None,
            current_session_token=None,
        )


@pytest.mark.asyncio
async def test_userinfo_subject_mismatch(
    db_session: AsyncSession,
    settings,
    token_encryptor: TokenEncryptor,
    static_jwks: StaticJwks,
    make_id_token,
) -> None:
    linkedin = FakeLinkedInClient(
        id_token=make_id_token(subject="sub-a"),
        userinfo=LinkedInUserInfo(sub="sub-b", name="Other", email=None, picture=None),
    )
    service = _service(
        db_session, settings, linkedin=linkedin, jwks=static_jwks, encryptor=token_encryptor
    )
    start = await service.start(existing_session_token=None)
    with pytest.raises(OAuthError, match="subject did not match"):
        await service.complete(
            code="auth-code",
            state=start.state,
            browser_nonce=start.browser_nonce,
            error=None,
            error_description=None,
            current_session_token=None,
        )


@pytest.mark.asyncio
async def test_successful_user_creation_and_token_encryption(
    db_session: AsyncSession,
    settings,
    token_encryptor: TokenEncryptor,
    static_jwks: StaticJwks,
    make_id_token,
) -> None:
    access = "linkedin-access-token-secret"
    linkedin = FakeLinkedInClient(id_token=make_id_token(subject="sub-new"), access_token=access)
    linkedin.userinfo = LinkedInUserInfo(
        sub="sub-new", name="Grace Hopper", email="grace@example.com", picture=None
    )
    service = _service(
        db_session, settings, linkedin=linkedin, jwks=static_jwks, encryptor=token_encryptor
    )
    start = await service.start(existing_session_token=None)
    result = await service.complete(
        code="auth-code",
        state=start.state,
        browser_nonce=start.browser_nonce,
        error=None,
        error_description=None,
        current_session_token=None,
    )

    assert result.user.linkedin_subject == "sub-new"
    assert result.user.display_name == "Grace Hopper"
    connection = (
        await db_session.execute(
            select(LinkedInConnection).where(LinkedInConnection.user_id == result.user.id)
        )
    ).scalar_one()
    assert connection.encrypted_access_token is not None
    assert access not in connection.encrypted_access_token
    assert token_encryptor.decrypt(connection.encrypted_access_token) == access
    assert connection.granted_scopes == LINKEDIN_SCOPES


@pytest.mark.asyncio
async def test_reconnect_rejects_different_linkedin_identity(
    db_session: AsyncSession,
    settings,
    token_encryptor: TokenEncryptor,
    static_jwks: StaticJwks,
    make_id_token,
) -> None:
    user, raw_token = await seed_user_with_session(
        db_session, encryptor=token_encryptor, subject="sub-existing"
    )
    linkedin = FakeLinkedInClient(
        id_token=make_id_token(subject="sub-other"),
        userinfo=LinkedInUserInfo(sub="sub-other", name="Other", email=None, picture=None),
    )
    service = _service(
        db_session, settings, linkedin=linkedin, jwks=static_jwks, encryptor=token_encryptor
    )
    start = await service.start(existing_session_token=raw_token)
    with pytest.raises(ConflictError, match="does not match the signed-in"):
        await service.complete(
            code="auth-code",
            state=start.state,
            browser_nonce=start.browser_nonce,
            error=None,
            error_description=None,
            current_session_token=raw_token,
        )
    assert user.linkedin_subject == "sub-existing"


@pytest.mark.asyncio
async def test_http_authorize_sets_nonce_cookie_and_redirects(
    db_client,
    app: FastAPI,
    static_jwks: StaticJwks,
    make_id_token,
) -> None:
    app.state.linkedin_client = FakeLinkedInClient(id_token=make_id_token())
    app.state.oidc_validator = LinkedInOidcValidator(
        client_id=LINKEDIN_CLIENT_ID, jwks_client=static_jwks
    )
    response = await db_client.get("/api/v1/auth/linkedin", follow_redirects=False)
    assert response.status_code == 302
    assert response.headers["location"].startswith(
        "https://www.linkedin.com/oauth/v2/authorization?"
    )
    assert OAUTH_NONCE_COOKIE in response.headers.get("set-cookie", "")


@pytest.mark.asyncio
async def test_http_callback_success_sets_session_cookie(
    db_client,
    app: FastAPI,
    db_session: AsyncSession,
    settings,
    token_encryptor: TokenEncryptor,
    static_jwks: StaticJwks,
    make_id_token,
) -> None:
    linkedin = FakeLinkedInClient(id_token=make_id_token(subject="sub-http"))
    linkedin.userinfo = LinkedInUserInfo(sub="sub-http", name="HTTP User", email=None, picture=None)
    app.state.linkedin_client = linkedin
    app.state.oidc_validator = LinkedInOidcValidator(
        client_id=LINKEDIN_CLIENT_ID, jwks_client=static_jwks
    )

    start = await _service(
        db_session, settings, linkedin=linkedin, jwks=static_jwks, encryptor=token_encryptor
    ).start(existing_session_token=None)

    db_client.cookies.set(OAUTH_NONCE_COOKIE, start.browser_nonce)
    response = await db_client.get(
        "/api/v1/auth/linkedin/callback",
        params={"code": "auth-code", "state": start.state},
        follow_redirects=False,
    )
    assert response.status_code == 302
    assert response.headers["location"].startswith(
        "http://localhost:3000/connections?oauth=success"
    )
    assert SESSION_COOKIE in response.headers.get("set-cookie", "")
    users = (await db_session.execute(select(User))).scalars().all()
    assert len(users) == 1


@pytest.mark.asyncio
async def test_me_and_connection_endpoints(
    db_client,
    db_session: AsyncSession,
    token_encryptor: TokenEncryptor,
) -> None:
    _user, raw = await seed_user_with_session(db_session, encryptor=token_encryptor)
    me = await db_client.get("/api/v1/auth/me", headers=session_cookie_header(raw))
    assert me.status_code == 200
    body = me.json()
    assert body["display_name"] == "Ada Lovelace"
    assert "token" not in body
    assert "access" not in str(body).lower() or "linkedin_subject" in body

    connection = await db_client.get(
        "/api/v1/connections/linkedin", headers=session_cookie_header(raw)
    )
    assert connection.status_code == 200
    payload = connection.json()
    assert payload["connected"] is True
    assert "encrypted" not in payload
    assert "access_token" not in payload
    assert LINKEDIN_SCOPES.split()[0] in payload["granted_scopes"]


@pytest.mark.asyncio
async def test_unauthorized_access(db_client) -> None:
    assert (await db_client.get("/api/v1/auth/me")).status_code == 401
    assert (await db_client.get("/api/v1/connections/linkedin")).status_code == 401


@pytest.mark.asyncio
async def test_logout_revokes_session(
    db_client,
    db_session: AsyncSession,
    token_encryptor: TokenEncryptor,
) -> None:
    _user, raw = await seed_user_with_session(db_session, encryptor=token_encryptor)
    response = await db_client.post(
        "/api/v1/auth/logout",
        headers={**session_cookie_header(raw), "Origin": ALLOWED_ORIGIN},
    )
    assert response.status_code == 204
    assert (
        await db_client.get("/api/v1/auth/me", headers=session_cookie_header(raw))
    ).status_code == 401


@pytest.mark.asyncio
async def test_disconnect_clears_token_preserves_user(
    db_client,
    db_session: AsyncSession,
    token_encryptor: TokenEncryptor,
) -> None:
    user, raw = await seed_user_with_session(db_session, encryptor=token_encryptor)
    response = await db_client.post(
        "/api/v1/connections/linkedin/disconnect",
        headers={**session_cookie_header(raw), "Origin": ALLOWED_ORIGIN},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["connected"] is False
    assert payload["disconnect_is_local_only"] is True

    await db_session.refresh(user)
    assert user.id is not None
    connection = (
        await db_session.execute(
            select(LinkedInConnection).where(LinkedInConnection.user_id == user.id)
        )
    ).scalar_one()
    assert connection.encrypted_access_token is None
    assert connection.connection_status == "disconnected"


@pytest.mark.asyncio
async def test_user_isolation(
    db_client,
    db_session: AsyncSession,
    token_encryptor: TokenEncryptor,
) -> None:
    _a, token_a = await seed_user_with_session(
        db_session, encryptor=token_encryptor, subject="sub-a", display_name="User A"
    )
    _b, token_b = await seed_user_with_session(
        db_session, encryptor=token_encryptor, subject="sub-b", display_name="User B"
    )
    me_a = (await db_client.get("/api/v1/auth/me", headers=session_cookie_header(token_a))).json()
    me_b = (await db_client.get("/api/v1/auth/me", headers=session_cookie_header(token_b))).json()
    assert me_a["display_name"] == "User A"
    assert me_b["display_name"] == "User B"
    assert me_a["id"] != me_b["id"]


@pytest.mark.asyncio
async def test_origin_rejected_on_logout(db_client, db_session, token_encryptor) -> None:
    _user, raw = await seed_user_with_session(db_session, encryptor=token_encryptor)
    response = await db_client.post(
        "/api/v1/auth/logout",
        headers={**session_cookie_header(raw), "Origin": "https://evil.example"},
    )
    assert response.status_code == 403
