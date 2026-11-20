"""Async SQLAlchemy engine and session construction."""

from sqlalchemy import URL
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.core.config import Settings


def build_database_url(settings: Settings) -> URL:
    """Assemble the asyncpg URL from discrete settings.

    `URL.create` escapes special characters in credentials and masks the password
    whenever the URL is rendered with `str()` or `repr()`.
    """
    return URL.create(
        drivername="postgresql+asyncpg",
        username=settings.postgres_user,
        password=settings.postgres_password.get_secret_value(),
        host=settings.postgres_host,
        port=settings.postgres_port,
        database=settings.postgres_db,
    )


def create_engine(settings: Settings) -> AsyncEngine:
    """Create the connection pool. No connection is opened until first use."""
    return create_async_engine(
        build_database_url(settings),
        pool_size=settings.db_pool_size,
        max_overflow=settings.db_max_overflow,
        # Detect connections dropped by the server before handing them to a request.
        pool_pre_ping=True,
        connect_args={"timeout": settings.db_connect_timeout_seconds},
    )


def create_session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False)
