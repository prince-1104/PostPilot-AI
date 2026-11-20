"""Shared async runtime helpers for Celery workers."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.core.logging import configure_logging
from app.db.session import create_engine, create_session_factory
from app.publishing.factory import build_publisher

_settings: Settings | None = None


def get_worker_settings() -> Settings:
    global _settings
    if _settings is None:
        _settings = get_settings()
        configure_logging(level=_settings.log_level, log_format=_settings.log_format)
    return _settings


def run_async[T](factory: Callable[[AsyncSession], Awaitable[T]]) -> T:
    """Run an async coroutine with a fresh DB session inside a Celery worker process.

    Each call uses ``asyncio.run`` with a **new** engine that is disposed before the
    loop closes. Reusing a process-global AsyncEngine across separate event loops
    deadlocks Celery prefork workers (tasks stay ``received`` forever).
    """

    async def _runner() -> T:
        settings = get_worker_settings()
        engine = create_engine(settings)
        session_factory = create_session_factory(engine)
        try:
            async with session_factory() as session:
                return await factory(session)
        finally:
            await engine.dispose()

    return asyncio.run(_runner())


def get_publisher():
    return build_publisher(get_worker_settings())
