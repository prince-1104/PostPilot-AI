"""Application session creation, expiration, and revocation."""

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import TokenEncryptor, hash_token
from app.models import AuthSession, User
from app.services.sessions import SessionService
from tests.conftest import seed_user_with_session, session_cookie_header


@pytest.mark.asyncio
async def test_create_and_resolve_session(db_session: AsyncSession) -> None:
    now = datetime.now(UTC)
    user = User(
        id=uuid4(),
        linkedin_subject="sub-session",
        display_name="Session User",
        email=None,
        avatar_url=None,
        created_at=now,
        updated_at=now,
    )
    db_session.add(user)
    await db_session.commit()

    service = SessionService(db_session, ttl_seconds=3600)
    issued = await service.create_session(user.id)
    await db_session.commit()

    resolved = await service.get_user_for_token(issued.raw_token)
    assert resolved is not None
    assert resolved.id == user.id
    assert issued.session.session_token_hash == hash_token(issued.raw_token)


@pytest.mark.asyncio
async def test_expired_session_is_rejected(db_session: AsyncSession) -> None:
    now = datetime.now(UTC)
    user = User(
        id=uuid4(),
        linkedin_subject="sub-expired",
        display_name="Expired",
        email=None,
        avatar_url=None,
        created_at=now,
        updated_at=now,
    )
    db_session.add(user)
    await db_session.flush()
    raw = "expired-session-token-value"
    db_session.add(
        AuthSession(
            id=uuid4(),
            user_id=user.id,
            session_token_hash=hash_token(raw),
            expires_at=now - timedelta(seconds=1),
            revoked_at=None,
            created_at=now,
        )
    )
    await db_session.commit()

    resolved = await SessionService(db_session, ttl_seconds=3600).get_user_for_token(raw)
    assert resolved is None


@pytest.mark.asyncio
async def test_revoked_session_is_rejected(db_session: AsyncSession) -> None:
    now = datetime.now(UTC)
    user = User(
        id=uuid4(),
        linkedin_subject="sub-revoked",
        display_name="Revoked",
        email=None,
        avatar_url=None,
        created_at=now,
        updated_at=now,
    )
    db_session.add(user)
    await db_session.flush()
    raw = "revoked-session-token-value"
    db_session.add(
        AuthSession(
            id=uuid4(),
            user_id=user.id,
            session_token_hash=hash_token(raw),
            expires_at=now + timedelta(hours=1),
            revoked_at=now,
            created_at=now,
        )
    )
    await db_session.commit()

    resolved = await SessionService(db_session, ttl_seconds=3600).get_user_for_token(raw)
    assert resolved is None


@pytest.mark.asyncio
async def test_http_expired_session_returns_401(
    db_client,
    db_session: AsyncSession,
    token_encryptor: TokenEncryptor,
) -> None:
    user, raw = await seed_user_with_session(db_session, encryptor=token_encryptor)
    from sqlalchemy import select

    session_row = (
        await db_session.execute(
            select(AuthSession).where(AuthSession.session_token_hash == hash_token(raw))
        )
    ).scalar_one()
    session_row.expires_at = datetime.now(UTC) - timedelta(seconds=5)
    await db_session.commit()

    response = await db_client.get("/api/v1/auth/me", headers=session_cookie_header(raw))
    assert response.status_code == 401
    assert user.display_name == "Ada Lovelace"
