"""Shared test fixtures.

Unit tests never read the developer's environment: every Settings-related variable is
removed first, and settings are built from explicit values. The database settings
point at a closed local port, so any accidental PostgreSQL access fails fast.

Auth tests that need persistence use an in-memory SQLite database instead.
"""

from __future__ import annotations

import base64
import io
import logging
import secrets
from collections.abc import AsyncIterator, Callable
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import httpx
import pytest
import structlog
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi import FastAPI
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.core.config import Settings
from app.core.cookies import SESSION_COOKIE
from app.core.security import TokenEncryptor, hash_token
from app.db.base import Base
from app.main import create_app
from app.models import AuthSession, LinkedInConnection, ScheduledPost, User
from app.models.enums import ConnectionStatus

ALLOWED_ORIGIN = "http://localhost:3000"
WEB_BASE_URL = "http://localhost:3000"
LINKEDIN_REDIRECT_URI = "http://localhost:8000/api/v1/auth/linkedin/callback"
LINKEDIN_CLIENT_ID = "test-linkedin-client-id"
LINKEDIN_SCOPES = "openid profile email w_member_social"

SettingsFactory = Callable[..., Settings]


@pytest.fixture(autouse=True)
def _isolate_environment(request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch) -> None:
    """Remove ambient configuration so unit tests are deterministic."""
    if request.node.get_closest_marker("integration"):
        return
    for field_name in Settings.model_fields:
        monkeypatch.delenv(field_name.upper(), raising=False)


@pytest.fixture
def encryption_key_b64() -> str:
    return base64.b64encode(secrets.token_bytes(32)).decode("ascii")


@pytest.fixture
def settings_factory(unused_tcp_port: int, encryption_key_b64: str) -> SettingsFactory:
    """Build valid settings, with keyword overrides for the case under test."""

    def factory(**overrides: object) -> Settings:
        values: dict[str, object] = {
            "app_env": "test",
            "log_format": "json",
            "postgres_host": "127.0.0.1",
            # Nothing listens here, so connection attempts are refused.
            "postgres_port": unused_tcp_port,
            "postgres_db": "postpilot_test",
            "postgres_user": "postpilot_test",
            "postgres_password": secrets.token_hex(16),
            "db_connect_timeout_seconds": 1.0,
            "readiness_timeout_seconds": 2.0,
            "cors_allowed_origins": [ALLOWED_ORIGIN],
            "linkedin_client_id": LINKEDIN_CLIENT_ID,
            "linkedin_client_secret": secrets.token_hex(16),
            "linkedin_redirect_uri": LINKEDIN_REDIRECT_URI,
            "linkedin_scopes": LINKEDIN_SCOPES,
            "token_encryption_key": encryption_key_b64,
            "web_base_url": WEB_BASE_URL,
            "cookie_secure": False,
            "session_ttl_seconds": 3600,
            "oauth_state_ttl_seconds": 600,
            "redis_host": "127.0.0.1",
            "redis_port": 6379,
            "redis_password": secrets.token_hex(16),
            "publish_provider": "fake",
        }
        values.update(overrides)
        return Settings(**values)

    return factory


@pytest.fixture
def settings(settings_factory: SettingsFactory) -> Settings:
    return settings_factory()


@pytest.fixture
def token_encryptor(settings: Settings) -> TokenEncryptor:
    return TokenEncryptor.from_settings_value(settings.token_encryption_key)


@pytest.fixture
def app(settings: Settings) -> FastAPI:
    return create_app(settings)


@pytest.fixture
def log_output(app: FastAPI) -> io.StringIO:
    """Redirect the application's log handler to a buffer the test can read.

    `capsys` cannot be used for this: pytest swaps its stream between the setup and
    call phases, while the handler is bound to a stream when the app is created.
    """
    buffer = io.StringIO()
    app_handlers = [
        handler
        for handler in logging.getLogger().handlers
        if isinstance(handler, logging.StreamHandler)
        and isinstance(handler.formatter, structlog.stdlib.ProcessorFormatter)
    ]
    assert len(app_handlers) == 1, "expected exactly one application log handler"
    app_handlers[0].setStream(buffer)
    return buffer


@pytest.fixture
async def client(app: FastAPI) -> AsyncIterator[httpx.AsyncClient]:
    """HTTP client bound to the app in-process, with startup and shutdown executed."""
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            yield client


@pytest.fixture
async def sqlite_engine() -> AsyncIterator[AsyncEngine]:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    try:
        yield engine
    finally:
        await engine.dispose()


@pytest.fixture
async def db_session(sqlite_engine: AsyncEngine) -> AsyncIterator[AsyncSession]:
    factory = async_sessionmaker(sqlite_engine, expire_on_commit=False)
    async with factory() as session:
        yield session


@pytest.fixture
async def db_client(app: FastAPI, sqlite_engine: AsyncEngine) -> AsyncIterator[httpx.AsyncClient]:
    """ASGI client whose session factory points at the in-memory SQLite database."""
    async with app.router.lifespan_context(app):
        app.state.session_factory = async_sessionmaker(sqlite_engine, expire_on_commit=False)
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            yield client


@pytest.fixture
def rsa_keys() -> tuple[rsa.RSAPrivateKey, rsa.RSAPublicKey]:
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    return private_key, private_key.public_key()


@pytest.fixture
def make_id_token(rsa_keys: tuple[rsa.RSAPrivateKey, rsa.RSAPublicKey]):
    private_key, _ = rsa_keys

    def factory(
        *,
        subject: str = "linkedin-sub-1",
        audience: str = LINKEDIN_CLIENT_ID,
        issuer: str = "https://www.linkedin.com/oauth",
        expires_delta: timedelta = timedelta(hours=1),
        issued_delta: timedelta = timedelta(0),
        algorithm: str = "RS256",
        key: rsa.RSAPrivateKey | None = None,
    ) -> str:
        import jwt

        now = datetime.now(UTC)
        payload = {
            "sub": subject,
            "aud": audience,
            "iss": issuer,
            "iat": int((now + issued_delta).timestamp()),
            "exp": int((now + expires_delta).timestamp()),
        }
        return jwt.encode(payload, key or private_key, algorithm=algorithm)

    return factory


class StaticJwks:
    """Test double that always returns the fixture RSA public key."""

    def __init__(self, public_key: rsa.RSAPublicKey) -> None:
        self._public_key = public_key

    def get_signing_key_from_jwt(self, token: str) -> object:
        class _Key:
            def __init__(self, key: rsa.RSAPublicKey) -> None:
                self.key = key

        return _Key(self._public_key)


@pytest.fixture
def static_jwks(rsa_keys: tuple[rsa.RSAPrivateKey, rsa.RSAPublicKey]) -> StaticJwks:
    return StaticJwks(rsa_keys[1])


async def seed_user_with_session(
    session: AsyncSession,
    *,
    encryptor: TokenEncryptor,
    subject: str = "linkedin-sub-1",
    display_name: str = "Ada Lovelace",
    with_connection: bool = True,
    token_expired: bool = False,
    granted_scopes: str = LINKEDIN_SCOPES,
    token_expires_at: datetime | None = None,
) -> tuple[User, str]:
    """Insert a user (and optional connection) and return ``(user, raw_session_token)``."""
    user, raw_token, _connection = await seed_user_session_and_connection(
        session,
        encryptor=encryptor,
        subject=subject,
        display_name=display_name,
        with_connection=with_connection,
        token_expired=token_expired,
        granted_scopes=granted_scopes,
        token_expires_at=token_expires_at,
    )
    return user, raw_token


async def seed_user_session_and_connection(
    session: AsyncSession,
    *,
    encryptor: TokenEncryptor,
    subject: str = "linkedin-sub-1",
    display_name: str = "Ada Lovelace",
    with_connection: bool = True,
    token_expired: bool = False,
    granted_scopes: str = LINKEDIN_SCOPES,
    token_expires_at: datetime | None = None,
) -> tuple[User, str, LinkedInConnection | None]:
    """Insert a user, session, and optional connection; return all three."""
    now = datetime.now(UTC)
    user = User(
        id=uuid4(),
        linkedin_subject=subject,
        display_name=display_name,
        email="ada@example.com",
        avatar_url="https://example.com/ada.png",
        created_at=now,
        updated_at=now,
    )
    session.add(user)
    await session.flush()

    connection: LinkedInConnection | None = None
    if with_connection:
        if token_expires_at is not None:
            expires = token_expires_at
        elif token_expired:
            expires = now - timedelta(hours=1)
        else:
            expires = now + timedelta(days=30)
        connection = LinkedInConnection(
            id=uuid4(),
            user_id=user.id,
            provider_subject=subject,
            encrypted_access_token=encryptor.encrypt("linkedin-access-token"),
            token_expires_at=expires,
            granted_scopes=granted_scopes,
            connection_status=(
                ConnectionStatus.REAUTH_REQUIRED.value
                if token_expired
                else ConnectionStatus.CONNECTED.value
            ),
            created_at=now,
            updated_at=now,
        )
        session.add(connection)

    raw_token = secrets.token_urlsafe(32)
    session.add(
        AuthSession(
            id=uuid4(),
            user_id=user.id,
            session_token_hash=hash_token(raw_token),
            expires_at=now + timedelta(hours=1),
            revoked_at=None,
            created_at=now,
        )
    )
    await session.commit()
    return user, raw_token, connection


def session_cookie_header(raw_token: str) -> dict[str, str]:
    return {"Cookie": f"{SESSION_COOKIE}={raw_token}"}


def stamp_publish_approval(
    post: ScheduledPost, *, approved_by, clock: datetime | None = None
) -> None:
    """Mark a seeded post as user-approved for LinkedIn publishing tests."""
    from app.publishing.authorization import apply_publish_approval

    apply_publish_approval(
        post,
        approved_by=approved_by,
        clock=clock or datetime.now(UTC),
    )
