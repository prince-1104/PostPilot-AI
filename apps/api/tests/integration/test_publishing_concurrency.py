"""PostgreSQL concurrency tests for Phase 4A publishing claims."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import Settings
from app.core.security import TokenEncryptor
from app.db.session import create_engine, create_session_factory
from app.models import PublishAttempt, ScheduledPost
from app.models.enums import PostStatus
from app.publishing.fake import FakeLinkedInPublisher
from app.services.publishing.claim import ClaimService
from app.services.publishing.executor import run_publish_pipeline
from tests.conftest import seed_user_session_and_connection

pytestmark = pytest.mark.integration


@pytest.fixture
async def pg_factory() -> AsyncIterator[tuple[async_sessionmaker[AsyncSession], Settings]]:
    settings = Settings()
    engine = create_engine(settings)
    factory = create_session_factory(engine)
    yield factory, settings
    await engine.dispose()


@pytest.mark.asyncio
async def test_two_workers_race_single_claim(
    pg_factory: tuple[async_sessionmaker[AsyncSession], Settings],
) -> None:
    factory, settings = pg_factory
    encryptor = TokenEncryptor.from_settings_value(settings.token_encryption_key)
    async with factory() as session:
        user, _raw, connection = await seed_user_session_and_connection(
            session, encryptor=encryptor, subject=f"race-{uuid4()}"
        )
        assert connection is not None
        now = datetime.now(UTC)
        post = ScheduledPost(
            id=uuid4(),
            user_id=user.id,
            linkedin_connection_id=connection.id,
            content="race",
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

    async def claim_once(worker: str):
        async with factory() as session:
            return await ClaimService(session, settings=settings).claim(
                post_id=post_id, worker_id=worker, celery_task_id=worker
            )

    first, second = await asyncio.gather(claim_once("w1"), claim_once("w2"))
    winners = [c for c in (first, second) if c is not None]
    assert len(winners) == 1

    async with factory() as session:
        attempts = (
            await session.execute(select(PublishAttempt).where(PublishAttempt.post_id == post_id))
        ).scalars().all()
        row = (
            await session.execute(select(ScheduledPost).where(ScheduledPost.id == post_id))
        ).scalar_one()
    assert len(attempts) == 1
    assert row.status == PostStatus.PROCESSING.value
    assert row.attempt_count == 1


@pytest.mark.asyncio
async def test_duplicate_task_delivery_publishes_once(
    pg_factory: tuple[async_sessionmaker[AsyncSession], Settings],
) -> None:
    factory, settings = pg_factory
    encryptor = TokenEncryptor.from_settings_value(settings.token_encryption_key)
    async with factory() as session:
        user, _raw, connection = await seed_user_session_and_connection(
            session, encryptor=encryptor, subject=f"dup-{uuid4()}"
        )
        assert connection is not None
        now = datetime.now(UTC)
        post = ScheduledPost(
            id=uuid4(),
            user_id=user.id,
            linkedin_connection_id=connection.id,
            content="[[fake:success]]",
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

    async def execute_once(worker: str) -> str:
        async with factory() as session:
            return await run_publish_pipeline(
                session,
                settings=settings,
                publisher=FakeLinkedInPublisher(),
                post_id=post_id,
                worker_id=worker,
                celery_task_id=worker,
            )

    results = await asyncio.gather(execute_once("a"), execute_once("b"), execute_once("c"))
    assert results.count(PostStatus.PUBLISHED.value) == 1
    assert results.count("skipped") == 2

    async with factory() as session:
        row = (
            await session.execute(select(ScheduledPost).where(ScheduledPost.id == post_id))
        ).scalar_one()
        attempts = (
            await session.execute(select(PublishAttempt).where(PublishAttempt.post_id == post_id))
        ).scalars().all()
    assert row.status == PostStatus.PUBLISHED.value
    assert len(attempts) == 1
