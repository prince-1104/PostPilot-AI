"""Health checks against backing services."""

import asyncio

import structlog
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import DependencyUnavailableError

logger = structlog.get_logger(__name__)


async def check_database(session: AsyncSession, *, timeout_seconds: float) -> None:
    """Run a real round trip to PostgreSQL.

    Raises:
        DependencyUnavailableError: the query failed or did not finish in time.
    """
    try:
        async with asyncio.timeout(timeout_seconds):
            await session.execute(text("SELECT 1"))
    # SQLAlchemyError covers driver and pool failures, OSError covers refused or
    # unreachable sockets, and TimeoutError covers both connect and query timeouts.
    except (SQLAlchemyError, OSError, TimeoutError) as exc:
        logger.warning(
            "readiness.database_unavailable",
            error_type=type(exc).__name__,
            error=str(exc),
        )
        raise DependencyUnavailableError("PostgreSQL is not reachable.") from exc
