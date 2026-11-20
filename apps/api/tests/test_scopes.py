"""LinkedIn scope parsing and OAuth grant verification."""

from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import OAuthError
from app.core.security import TokenEncryptor
from app.integrations.linkedin import (
    LinkedInIntrospectionError,
    LinkedInOidcValidator,
    LinkedInTokenIntrospection,
    LinkedInUserInfo,
    format_granted_scopes,
    parse_introspection_scopes,
    parse_token_exchange_scopes,
)
from app.services.oauth import OAuthService
from tests.conftest import LINKEDIN_CLIENT_ID, LINKEDIN_SCOPES, StaticJwks
from tests.fakes import FakeLinkedInClient

REQUIRED = frozenset(LINKEDIN_SCOPES.split())


def test_parse_token_exchange_space_delimited() -> None:
    assert parse_token_exchange_scopes("openid profile email w_member_social") == REQUIRED


def test_parse_token_exchange_url_encoded_spaces() -> None:
    raw = "openid%20profile%20email%20w_member_social"
    assert parse_token_exchange_scopes(raw) == REQUIRED


def test_parse_introspection_comma_delimited() -> None:
    raw = "openid,profile,email,w_member_social"
    assert parse_introspection_scopes(raw) == REQUIRED


def test_parse_formats_are_not_interchangeable() -> None:
    # Comma list must not be treated as a single space-delimited token blob.
    comma = "openid,profile,email,w_member_social"
    assert parse_token_exchange_scopes(comma) == frozenset({comma})
    assert parse_introspection_scopes("openid profile email") == frozenset({"openid profile email"})


def test_format_granted_scopes_is_stable() -> None:
    assert format_granted_scopes(REQUIRED) == " ".join(sorted(REQUIRED))


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
async def test_granted_space_delimited_scopes_succeed(
    db_session: AsyncSession,
    settings,
    token_encryptor: TokenEncryptor,
    static_jwks: StaticJwks,
    make_id_token,
) -> None:
    linkedin = FakeLinkedInClient(
        id_token=make_id_token(subject="sub-scopes"),
        scope="openid profile email w_member_social",
        userinfo=LinkedInUserInfo(sub="sub-scopes", name="Scoped", email=None, picture=None),
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
    assert result.user.linkedin_subject == "sub-scopes"
    assert linkedin.introspected_tokens == []


@pytest.mark.asyncio
async def test_url_encoded_token_exchange_scopes_succeed(
    db_session: AsyncSession,
    settings,
    token_encryptor: TokenEncryptor,
    static_jwks: StaticJwks,
    make_id_token,
) -> None:
    linkedin = FakeLinkedInClient(
        id_token=make_id_token(subject="sub-encoded"),
        scope="openid%20profile%20email%20w_member_social",
        userinfo=LinkedInUserInfo(sub="sub-encoded", name="Encoded", email=None, picture=None),
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
    assert result.user.linkedin_subject == "sub-encoded"


@pytest.mark.asyncio
async def test_missing_required_scopes_are_rejected(
    db_session: AsyncSession,
    settings,
    token_encryptor: TokenEncryptor,
    static_jwks: StaticJwks,
    make_id_token,
) -> None:
    linkedin = FakeLinkedInClient(
        id_token=make_id_token(subject="sub-partial"),
        scope="openid profile",
        userinfo=LinkedInUserInfo(sub="sub-partial", name="Partial", email=None, picture=None),
        # Introspection confirms the same incomplete grant (provider denial).
        introspection=LinkedInTokenIntrospection(
            active=True,
            client_id=LINKEDIN_CLIENT_ID,
            scope="openid,profile",
            status="active",
        ),
    )
    service = _service(
        db_session, settings, linkedin=linkedin, jwks=static_jwks, encryptor=token_encryptor
    )
    start = await service.start(existing_session_token=None)
    with pytest.raises(OAuthError, match="required scopes"):
        await service.complete(
            code="auth-code",
            state=start.state,
            browser_nonce=start.browser_nonce,
            error=None,
            error_description=None,
            current_session_token=None,
        )
    assert linkedin.introspected_tokens == ["li-access-token"]


@pytest.mark.asyncio
async def test_empty_scope_string_falls_back_to_introspection(
    db_session: AsyncSession,
    settings,
    token_encryptor: TokenEncryptor,
    static_jwks: StaticJwks,
    make_id_token,
) -> None:
    linkedin = FakeLinkedInClient(
        id_token=make_id_token(subject="sub-empty"),
        scope="",
        userinfo=LinkedInUserInfo(sub="sub-empty", name="Empty", email=None, picture=None),
        introspection=LinkedInTokenIntrospection(
            active=True,
            client_id=LINKEDIN_CLIENT_ID,
            scope="openid,profile,email,w_member_social",
            status="active",
        ),
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
    assert result.user.linkedin_subject == "sub-empty"
    assert linkedin.introspected_tokens == ["li-access-token"]


@pytest.mark.asyncio
async def test_comma_delimited_token_exchange_scope_uses_introspection(
    db_session: AsyncSession,
    settings,
    token_encryptor: TokenEncryptor,
    static_jwks: StaticJwks,
    make_id_token,
) -> None:
    """Live LinkedIn OIDC returns a 36-char comma list in token-exchange scope."""
    linkedin = FakeLinkedInClient(
        id_token=make_id_token(subject="sub-comma-token"),
        scope="openid,profile,email,w_member_social",
        userinfo=LinkedInUserInfo(sub="sub-comma-token", name="Comma", email=None, picture=None),
        introspection=LinkedInTokenIntrospection(
            active=True,
            client_id=LINKEDIN_CLIENT_ID,
            scope="openid,profile,email,w_member_social",
            status="active",
        ),
    )
    assert len(linkedin.scope or "") == 36
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
    assert result.user.linkedin_subject == "sub-comma-token"
    assert linkedin.introspected_tokens == ["li-access-token"]


@pytest.mark.asyncio
async def test_absent_scope_uses_introspection_comma_scopes(
    db_session: AsyncSession,
    settings,
    token_encryptor: TokenEncryptor,
    static_jwks: StaticJwks,
    make_id_token,
) -> None:
    linkedin = FakeLinkedInClient(
        id_token=make_id_token(subject="sub-introspect"),
        scope=None,
        userinfo=LinkedInUserInfo(
            sub="sub-introspect", name="Introspect", email=None, picture=None
        ),
        introspection=LinkedInTokenIntrospection(
            active=True,
            client_id=LINKEDIN_CLIENT_ID,
            scope="openid,profile,email,w_member_social",
            status="active",
        ),
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
    assert result.user.linkedin_subject == "sub-introspect"
    assert linkedin.introspected_tokens == ["li-access-token"]


@pytest.mark.asyncio
async def test_failed_introspection_is_rejected(
    db_session: AsyncSession,
    settings,
    token_encryptor: TokenEncryptor,
    static_jwks: StaticJwks,
    make_id_token,
) -> None:
    linkedin = FakeLinkedInClient(
        id_token=make_id_token(subject="sub-fail-introspect"),
        scope=None,
        userinfo=LinkedInUserInfo(sub="sub-fail-introspect", name="Fail", email=None, picture=None),
        introspection_error=LinkedInIntrospectionError(
            "LinkedIn rejected the token introspection request."
        ),
    )
    service = _service(
        db_session, settings, linkedin=linkedin, jwks=static_jwks, encryptor=token_encryptor
    )
    start = await service.start(existing_session_token=None)
    with pytest.raises(OAuthError, match="introspection"):
        await service.complete(
            code="auth-code",
            state=start.state,
            browser_nonce=start.browser_nonce,
            error=None,
            error_description=None,
            current_session_token=None,
        )


@pytest.mark.asyncio
async def test_introspection_client_id_mismatch_is_rejected(
    db_session: AsyncSession,
    settings,
    token_encryptor: TokenEncryptor,
    static_jwks: StaticJwks,
    make_id_token,
) -> None:
    linkedin = FakeLinkedInClient(
        id_token=make_id_token(subject="sub-mismatch"),
        scope=None,
        userinfo=LinkedInUserInfo(sub="sub-mismatch", name="Mismatch", email=None, picture=None),
        introspection=LinkedInTokenIntrospection(
            active=True,
            client_id="some-other-client",
            scope="openid,profile,email,w_member_social",
            status="active",
        ),
    )
    service = _service(
        db_session, settings, linkedin=linkedin, jwks=static_jwks, encryptor=token_encryptor
    )
    start = await service.start(existing_session_token=None)
    with pytest.raises(OAuthError, match="client ID"):
        await service.complete(
            code="auth-code",
            state=start.state,
            browser_nonce=start.browser_nonce,
            error=None,
            error_description=None,
            current_session_token=None,
        )


@pytest.mark.asyncio
async def test_introspection_without_scope_fails_securely(
    db_session: AsyncSession,
    settings,
    token_encryptor: TokenEncryptor,
    static_jwks: StaticJwks,
    make_id_token,
) -> None:
    linkedin = FakeLinkedInClient(
        id_token=make_id_token(subject="sub-no-scope"),
        scope=None,
        userinfo=LinkedInUserInfo(sub="sub-no-scope", name="NoScope", email=None, picture=None),
        introspection=LinkedInTokenIntrospection(
            active=True,
            client_id=LINKEDIN_CLIENT_ID,
            scope=None,
            status="active",
        ),
    )
    service = _service(
        db_session, settings, linkedin=linkedin, jwks=static_jwks, encryptor=token_encryptor
    )
    start = await service.start(existing_session_token=None)
    with pytest.raises(OAuthError, match="did not report granted scopes"):
        await service.complete(
            code="auth-code",
            state=start.state,
            browser_nonce=start.browser_nonce,
            error=None,
            error_description=None,
            current_session_token=None,
        )
