"""Shared async runtime helpers for Celery workers."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable

from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.core.config import Settings, get_settings
from app.core.logging import configure_logging
from app.db.session import create_engine, create_session_factory
from app.publishing.factory import build_publisher

_engine: AsyncEngine | None = None
_session_factory: async_sessionmaker[AsyncSession] | None = None
_settings: Settings | None = None


def get_worker_settings() -> Settings:
    global _settings
    if _settings is None:
        _settings = get_settings()
        configure_logging(level=_settings.log_level, log_format=_settings.log_format)
    return _settings


def get_session_factory() -> async_sessionmaker[AsyncSession]:
    global _engine, _session_factory
    if _session_factory is None:
        settings = get_worker_settings()
        _engine = create_engine(settings)
        _session_factory = create_session_factory(_engine)
    return _session_factory


def run_async[T](factory: Callable[[AsyncSession], Awaitable[T]]) -> T:
    """Run an async coroutine with a fresh DB session inside a Celery worker process."""

    async def _runner() -> T:
        session_factory = get_session_factory()
        async with session_factory() as session:
            return await factory(session)

    return asyncio.run(_runner())


def get_publisher():
    return build_publisher(get_worker_settings())
