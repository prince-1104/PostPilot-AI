"""Alembic environment for async migrations.

Connection details come from the same `Settings` object the API uses, so migrations
and the application can never point at different databases.
"""

import asyncio

from alembic import context
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

from app import models  # noqa: F401  # imported so model tables register on Base.metadata
from app.core.config import get_settings
from app.core.logging import configure_logging
from app.db.base import Base
from app.db.session import build_database_url

settings = get_settings()
configure_logging(level=settings.log_level, log_format=settings.log_format)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """Emit SQL to stdout without connecting (`alembic upgrade head --sql`)."""
    context.configure(
        dialect_name="postgresql",
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def _run_migrations(connection: Connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata)

    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online() -> None:
    """Connect with asyncpg and run migrations inside a transaction."""
    # NullPool: a migration run is a one-shot process and should not hold a pool.
    engine = create_async_engine(build_database_url(settings), poolclass=NullPool)
    try:
        async with engine.connect() as connection:
            await connection.run_sync(_run_migrations)
    finally:
        await engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_migrations_online())
