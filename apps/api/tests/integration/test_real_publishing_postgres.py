"""PostgreSQL persistence for Phase 4B real publisher (HTTP mocked)."""

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
from app.models import PublishAttempt, ScheduledPost
from app.models.enums import PostStatus
from app.publishing.real import RealLinkedInPublisher
from app.services.publishing.executor import run_publish_pipeline
from tests.conftest import seed_user_session_and_connection

pytestmark = pytest.mark.integration


@pytest.fixture
async def pg_factory() -> AsyncIterator[tuple[async_sessionmaker[AsyncSession], Settings]]:
    settings = Settings(
        publish_provider="linkedin",
        enable_real_publishing=True,
    )
    engine = create_engine(settings)
    factory = create_session_factory(engine)
    yield factory, settings
    await engine.dispose()


@pytest.mark.asyncio
async def test_real_provider_success_persists_on_postgres(
    pg_factory: tuple[async_sessionmaker[AsyncSession], Settings],
) -> None:
    factory, settings = pg_factory
    encryptor = TokenEncryptor.from_settings_value(settings.token_encryption_key)
    async with factory() as session:
        user, _raw, connection = await seed_user_session_and_connection(
            session, encryptor=encryptor, subject=f"pg-real-{uuid4()}"
        )
        assert connection is not None
        now = datetime.now(UTC)
        post = ScheduledPost(
            id=uuid4(),
            user_id=user.id,
            linkedin_connection_id=connection.id,
            content="postgres-real",
            scheduled_at=now - timedelta(minutes=1),
            timezone="UTC",
            status=PostStatus.SCHEDULED.value,
            idempotency_key=f"idem-{uuid4().hex[:12]}",
            request_fingerprint="fp",
            version=1,
            attempt_count=0,
            created_at=now,
            updated_at=now,
        )
        session.add(post)
        await session.commit()
        post_id = post.id

    calls = 0

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(
            201, headers={"x-restli-id": "urn:li:share:555444333222111"}
        )

    publisher = RealLinkedInPublisher(
        settings=settings,
        encryptor=encryptor,
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
    )

    async with factory() as session:
        result = await run_publish_pipeline(
            session,
            settings=settings,
            publisher=publisher,
            post_id=post_id,
            worker_id="pg-w1",
            celery_task_id="pg-t1",
        )
    assert result == PostStatus.PUBLISHED.value
    assert calls == 1

    async with factory() as session:
        row = (
            await session.execute(select(ScheduledPost).where(ScheduledPost.id == post_id))
        ).scalar_one()
        attempts = (
            await session.execute(select(PublishAttempt).where(PublishAttempt.post_id == post_id))
        ).scalars().all()
    assert row.status == PostStatus.PUBLISHED.value
    assert row.linkedin_post_urn == "urn:li:share:555444333222111"
    assert len(attempts) == 1


@pytest.mark.asyncio
async def test_concurrent_workers_single_real_api_call(
    pg_factory: tuple[async_sessionmaker[AsyncSession], Settings],
) -> None:
    factory, settings = pg_factory
    encryptor = TokenEncryptor.from_settings_value(settings.token_encryption_key)
    async with factory() as session:
        user, _raw, connection = await seed_user_session_and_connection(
            session, encryptor=encryptor, subject=f"pg-race-{uuid4()}"
        )
        assert connection is not None
        now = datetime.now(UTC)
        post = ScheduledPost(
            id=uuid4(),
            user_id=user.id,
            linkedin_connection_id=connection.id,
            content="race-real",
            scheduled_at=now - timedelta(minutes=1),
            timezone="UTC",
            status=PostStatus.SCHEDULED.value,
            idempotency_key=f"idem-{uuid4().hex[:12]}",
            request_fingerprint="fp",
            version=1,
            attempt_count=0,
            created_at=now,
            updated_at=now,
        )
        session.add(post)
        await session.commit()
        post_id = post.id

    calls = 0

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(
            201, headers={"x-restli-id": "urn:li:ugcPost:121212121212"}
        )

    def make_publisher() -> RealLinkedInPublisher:
        return RealLinkedInPublisher(
            settings=settings,
            encryptor=encryptor,
            http_client=httpx.Client(transport=httpx.MockTransport(handler)),
        )

    async def execute_once(worker: str) -> str:
        async with factory() as session:
            return await run_publish_pipeline(
                session,
                settings=settings,
                publisher=make_publisher(),
                post_id=post_id,
                worker_id=worker,
                celery_task_id=worker,
            )

    results = await asyncio.gather(execute_once("a"), execute_once("b"), execute_once("c"))
    assert results.count(PostStatus.PUBLISHED.value) == 1
    assert results.count("skipped") == 2
    assert calls == 1

    async with factory() as session:
        row = (
            await session.execute(select(ScheduledPost).where(ScheduledPost.id == post_id))
        ).scalar_one()
    assert row.linkedin_post_urn == "urn:li:ugcPost:121212121212"
