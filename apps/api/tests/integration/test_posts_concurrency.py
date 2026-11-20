"""Concurrent idempotent creates against real PostgreSQL."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import Settings
from app.core.security import TokenEncryptor
from app.db.session import create_engine, create_session_factory
from app.main import create_app
from app.models import ScheduledPost
from tests.conftest import ALLOWED_ORIGIN, seed_user_session_and_connection

pytestmark = pytest.mark.integration


PgEnv = tuple[httpx.AsyncClient, async_sessionmaker[AsyncSession], Settings]


@pytest.fixture
async def pg_env() -> AsyncIterator[PgEnv]:
    settings = Settings()
    app = create_app(settings)
    engine = create_engine(settings)
    factory = create_session_factory(engine)
    async with app.router.lifespan_context(app):
        # Use the same engine the app uses so inserts are visible.
        app.state.session_factory = factory
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            yield client, factory, settings
    await engine.dispose()


@pytest.mark.asyncio
async def test_concurrent_duplicate_idempotency_keys(
    pg_env: tuple[httpx.AsyncClient, async_sessionmaker[AsyncSession], Settings],
) -> None:
    client, factory, settings = pg_env
    encryptor = TokenEncryptor.from_settings_value(settings.token_encryption_key)
    subject = f"concurrent-{uuid4()}"
    async with factory() as session:
        _user, raw, connection = await seed_user_session_and_connection(
            session,
            encryptor=encryptor,
            subject=subject,
        )
    assert connection is not None
    when = datetime.now(UTC) + timedelta(hours=3)
    payload = {
        "content": "Concurrent create",
        "scheduled_at": when.isoformat(),
        "timezone": "UTC",
        "linkedin_connection_id": str(connection.id),
    }
    headers = {
        "Cookie": f"postpilot_session={raw}",
        "Origin": ALLOWED_ORIGIN,
        "Idempotency-Key": f"concurrent-key-{uuid4().hex[:12]}",
    }

    async def create_once() -> httpx.Response:
        return await client.post("/api/v1/posts", headers=headers, json=payload)

    results = await asyncio.gather(create_once(), create_once(), create_once())
    statuses = sorted(response.status_code for response in results)
    assert statuses == [201, 201, 201]
    ids = {response.json()["id"] for response in results}
    assert len(ids) == 1

    async with factory() as session:
        key = headers["Idempotency-Key"]
        rows = (
            await session.execute(select(ScheduledPost).where(ScheduledPost.idempotency_key == key))
        ).scalars().all()
    assert len(rows) == 1
