"""PostgreSQL multi-post scheduling and dispatch eligibility (mocked LinkedIn)."""

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
from app.publishing.gates import AUTH_GATE_RECHECK_SECONDS
from app.schemas.posts import UpdateScheduledPost
from app.services.posts import PostService
from app.services.publishing.dispatcher import DispatchService
from app.services.publishing.executor import run_publish_pipeline
from tests.conftest import seed_user_session_and_connection, stamp_publish_approval

pytestmark = pytest.mark.integration


@pytest.fixture
async def pg_factory() -> AsyncIterator[tuple[async_sessionmaker[AsyncSession], Settings]]:
    settings = Settings(
        publish_provider="fake",
        enable_real_publishing=False,
        live_publish_require_canary=False,
        live_publish_canary_post_ids=[],
        dispatch_batch_size=50,
    )
    engine = create_engine(settings)
    factory = create_session_factory(engine)
    yield factory, settings
    await engine.dispose()


def _approved_post(
    *,
    user_id,
    connection_id,
    content: str,
    scheduled_at: datetime,
    approved_by,
    next_attempt_at: datetime | None = None,
    attempt_count: int = 0,
    last_error_code: str | None = None,
) -> ScheduledPost:
    now = datetime.now(UTC)
    post = ScheduledPost(
        id=uuid4(),
        user_id=user_id,
        linkedin_connection_id=connection_id,
        content=content,
        scheduled_at=scheduled_at,
        timezone="UTC",
        status=PostStatus.SCHEDULED.value,
        idempotency_key=f"idem-{uuid4().hex}",
        request_fingerprint=f"fp-{uuid4().hex[:12]}",
        version=1,
        attempt_count=attempt_count,
        last_error_code=last_error_code,
        created_at=now,
        updated_at=now,
    )
    stamp_publish_approval(post, approved_by=approved_by, clock=now)
    # Approval clears gate holds; re-apply retry state after stamping when needed.
    post.next_attempt_at = next_attempt_at
    post.attempt_count = attempt_count
    post.last_error_code = last_error_code
    return post


@pytest.mark.asyncio
async def test_five_approved_posts_one_account_all_dispatch(
    pg_factory: tuple[async_sessionmaker[AsyncSession], Settings],
) -> None:
    factory, settings = pg_factory
    encryptor = TokenEncryptor.from_settings_value(settings.token_encryption_key)
    async with factory() as session:
        user, _raw, connection = await seed_user_session_and_connection(
            session, encryptor=encryptor, subject=f"multi5-{uuid4()}"
        )
        assert connection is not None
        now = datetime.now(UTC)
        posts = [
            _approved_post(
                user_id=user.id,
                connection_id=connection.id,
                content=f"[[fake:success]] multi-{i}",
                scheduled_at=now - timedelta(minutes=5 - i),
                approved_by=user.id,
            )
            for i in range(5)
        ]
        session.add_all(posts)
        await session.commit()
        post_ids = [p.id for p in posts]

    queued: list = []
    async with factory() as session:
        result = await DispatchService(
            session, settings=settings, enqueue=lambda pid: queued.append(pid) or "t"
        ).dispatch_due(now=datetime.now(UTC))
    # Shared Postgres may contain other due fixtures; require ours are all claimed.
    assert set(post_ids).issubset(set(queued))
    assert result["claimed"] >= 5

    for post_id in post_ids:
        async with factory() as session:
            outcome = await run_publish_pipeline(
                session,
                settings=settings,
                publisher=FakeLinkedInPublisher(),
                post_id=post_id,
                worker_id=f"w-{post_id}",
                celery_task_id=f"t-{post_id}",
            )
        assert outcome == PostStatus.PUBLISHED.value

    async with factory() as session:
        rows = (
            await session.execute(select(ScheduledPost).where(ScheduledPost.id.in_(post_ids)))
        ).scalars().all()
    assert {r.status for r in rows} == {PostStatus.PUBLISHED.value}
    assert all(r.linkedin_post_urn for r in rows)
    assert len({r.linkedin_post_urn for r in rows}) == 5


@pytest.mark.asyncio
async def test_three_posts_same_utc_instant_claimed_and_executed_once(
    pg_factory: tuple[async_sessionmaker[AsyncSession], Settings],
) -> None:
    factory, settings = pg_factory
    encryptor = TokenEncryptor.from_settings_value(settings.token_encryption_key)
    same_instant = datetime.now(UTC) - timedelta(seconds=30)
    async with factory() as session:
        user, _raw, connection = await seed_user_session_and_connection(
            session, encryptor=encryptor, subject=f"same-ts-{uuid4()}"
        )
        assert connection is not None
        posts = [
            _approved_post(
                user_id=user.id,
                connection_id=connection.id,
                content=f"[[fake:success]] same-{i}",
                scheduled_at=same_instant,
                approved_by=user.id,
            )
            for i in range(3)
        ]
        session.add_all(posts)
        await session.commit()
        post_ids = [p.id for p in posts]

    queued: list = []
    async with factory() as session:
        result = await DispatchService(
            session, settings=settings, enqueue=lambda pid: queued.append(pid) or "t"
        ).dispatch_due(now=datetime.now(UTC))
    assert set(post_ids).issubset(set(queued))
    assert result["claimed"] >= 3

    for post_id in post_ids:
        async with factory() as session:
            first = await run_publish_pipeline(
                session,
                settings=settings,
                publisher=FakeLinkedInPublisher(),
                post_id=post_id,
                worker_id="w1",
                celery_task_id=f"first-{post_id}",
            )
            second = await run_publish_pipeline(
                session,
                settings=settings,
                publisher=FakeLinkedInPublisher(),
                post_id=post_id,
                worker_id="w2",
                celery_task_id=f"dup-{post_id}",
            )
        assert first == PostStatus.PUBLISHED.value
        assert second == "skipped"

    async with factory() as session:
        attempts = (
            await session.execute(
                select(PublishAttempt).where(PublishAttempt.post_id.in_(post_ids))
            )
        ).scalars().all()
        rows = (
            await session.execute(select(ScheduledPost).where(ScheduledPost.id.in_(post_ids)))
        ).scalars().all()
    assert len(attempts) == 3
    assert all(r.status == PostStatus.PUBLISHED.value for r in rows)


@pytest.mark.asyncio
async def test_two_independent_users_isolated(
    pg_factory: tuple[async_sessionmaker[AsyncSession], Settings],
) -> None:
    factory, settings = pg_factory
    encryptor = TokenEncryptor.from_settings_value(settings.token_encryption_key)
    async with factory() as session:
        user_a, _raw_a, conn_a = await seed_user_session_and_connection(
            session, encryptor=encryptor, subject=f"user-a-{uuid4()}", display_name="User A"
        )
        user_b, _raw_b, conn_b = await seed_user_session_and_connection(
            session, encryptor=encryptor, subject=f"user-b-{uuid4()}", display_name="User B"
        )
        assert conn_a is not None
        assert conn_b is not None
        now = datetime.now(UTC)
        post_a = _approved_post(
            user_id=user_a.id,
            connection_id=conn_a.id,
            content="[[fake:success]] user-a",
            scheduled_at=now - timedelta(minutes=1),
            approved_by=user_a.id,
        )
        post_b = _approved_post(
            user_id=user_b.id,
            connection_id=conn_b.id,
            content="[[fake:success]] user-b",
            scheduled_at=now - timedelta(minutes=1),
            approved_by=user_b.id,
        )
        session.add_all([post_a, post_b])
        await session.commit()
        id_a, id_b = post_a.id, post_b.id
        uid_a, uid_b = user_a.id, user_b.id

    queued: list = []
    async with factory() as session:
        await DispatchService(
            session, settings=settings, enqueue=lambda pid: queued.append(pid) or "t"
        ).dispatch_due(now=datetime.now(UTC))
    assert {id_a, id_b}.issubset(set(queued))

    for post_id in (id_a, id_b):
        async with factory() as session:
            assert (
                await run_publish_pipeline(
                    session,
                    settings=settings,
                    publisher=FakeLinkedInPublisher(),
                    post_id=post_id,
                    worker_id=f"w-{post_id}",
                    celery_task_id=f"t-{post_id}",
                )
            ) == PostStatus.PUBLISHED.value

    async with factory() as session:
        row_a = (
            await session.execute(select(ScheduledPost).where(ScheduledPost.id == id_a))
        ).scalar_one()
        row_b = (
            await session.execute(select(ScheduledPost).where(ScheduledPost.id == id_b))
        ).scalar_one()
    assert row_a.user_id == uid_a
    assert row_b.user_id == uid_b
    assert row_a.linkedin_connection_id != row_b.linkedin_connection_id
    assert row_a.status == PostStatus.PUBLISHED.value
    assert row_b.status == PostStatus.PUBLISHED.value


@pytest.mark.asyncio
async def test_cancel_one_leaves_siblings_scheduled(
    pg_factory: tuple[async_sessionmaker[AsyncSession], Settings],
) -> None:
    factory, settings = pg_factory
    encryptor = TokenEncryptor.from_settings_value(settings.token_encryption_key)
    async with factory() as session:
        user, _raw, connection = await seed_user_session_and_connection(
            session, encryptor=encryptor, subject=f"cancel-sib-{uuid4()}"
        )
        assert connection is not None
        now = datetime.now(UTC)
        keep = _approved_post(
            user_id=user.id,
            connection_id=connection.id,
            content="keep-me",
            scheduled_at=now + timedelta(hours=2),
            approved_by=user.id,
            next_attempt_at=now + timedelta(days=7),
        )
        cancel_me = _approved_post(
            user_id=user.id,
            connection_id=connection.id,
            content="cancel-me",
            scheduled_at=now + timedelta(hours=3),
            approved_by=user.id,
            next_attempt_at=now + timedelta(days=7),
        )
        session.add_all([keep, cancel_me])
        await session.commit()
        keep_id, cancel_id = keep.id, cancel_me.id
        version = cancel_me.version

        service = PostService(session, settings=settings)
        cancelled = await service.cancel(
            user=user, post_id=cancel_id, expected_version=version
        )
        await session.commit()
        assert cancelled.status == PostStatus.CANCELLED.value
        assert cancelled.next_attempt_at is None

        cancel_row = (
            await session.execute(select(ScheduledPost).where(ScheduledPost.id == cancel_id))
        ).scalar_one()
        assert cancel_row.next_attempt_at is None
        assert cancel_row.dispatch_lease_until is None

        keep_row = (
            await session.execute(select(ScheduledPost).where(ScheduledPost.id == keep_id))
        ).scalar_one()
        assert keep_row.status == PostStatus.SCHEDULED.value
        assert keep_row.next_attempt_at is not None


@pytest.mark.asyncio
async def test_reschedule_one_does_not_affect_siblings(
    pg_factory: tuple[async_sessionmaker[AsyncSession], Settings],
) -> None:
    factory, settings = pg_factory
    encryptor = TokenEncryptor.from_settings_value(settings.token_encryption_key)
    async with factory() as session:
        user, _raw, connection = await seed_user_session_and_connection(
            session, encryptor=encryptor, subject=f"resched-{uuid4()}"
        )
        assert connection is not None
        now = datetime.now(UTC)
        sibling = _approved_post(
            user_id=user.id,
            connection_id=connection.id,
            content="sibling",
            scheduled_at=now + timedelta(hours=1),
            approved_by=user.id,
        )
        target = _approved_post(
            user_id=user.id,
            connection_id=connection.id,
            content="target",
            scheduled_at=now + timedelta(hours=2),
            approved_by=user.id,
        )
        session.add_all([sibling, target])
        await session.commit()
        sibling_id, target_id = sibling.id, target.id
        sibling_scheduled = sibling.scheduled_at
        version = target.version

        service = PostService(session, settings=settings)
        new_when = now + timedelta(hours=5)
        updated = await service.update(
            user=user,
            post_id=target_id,
            payload=UpdateScheduledPost(
                expected_version=version,
                content="target-rescheduled",
                scheduled_at=new_when,
                timezone="UTC",
                confirm_publish=True,
            ),
        )
        await session.commit()
        assert updated.scheduled_at == new_when
        assert updated.content == "target-rescheduled"

        sibling_row = (
            await session.execute(select(ScheduledPost).where(ScheduledPost.id == sibling_id))
        ).scalar_one()
        assert sibling_row.scheduled_at == sibling_scheduled
        assert sibling_row.content == "sibling"
        assert sibling_row.status == PostStatus.SCHEDULED.value


@pytest.mark.asyncio
async def test_canary_off_clears_stale_seven_day_deferral(
    pg_factory: tuple[async_sessionmaker[AsyncSession], Settings],
) -> None:
    factory, _base = pg_factory
    encryptor = TokenEncryptor.from_settings_value(_base.token_encryption_key)
    # Copy base settings so required secrets/env match the shared Postgres fixture.
    settings_off = _base.model_copy(
        update={
            "publish_provider": "linkedin",
            "enable_real_publishing": True,
            "live_publish_require_canary": False,
            "live_publish_canary_post_ids": [],
            "dispatch_batch_size": 500,
        }
    )
    async with factory() as session:
        user, _raw, connection = await seed_user_session_and_connection(
            session, encryptor=encryptor, subject=f"stale-canary-{uuid4()}"
        )
        assert connection is not None
        now = datetime.now(UTC)
        # Gate-tagged hold (not bare attempt_count==0) — matches production canary parks.
        parked = _approved_post(
            user_id=user.id,
            connection_id=connection.id,
            content="[[fake:success]] was-parked",
            scheduled_at=now - timedelta(days=30),
            approved_by=user.id,
            next_attempt_at=now + timedelta(days=7),
            attempt_count=0,
            last_error_code="live_publish_canary_blocked",
        )
        genuine_retry = _approved_post(
            user_id=user.id,
            connection_id=connection.id,
            content="genuine-retry",
            scheduled_at=now - timedelta(hours=1),
            approved_by=user.id,
            next_attempt_at=now + timedelta(hours=2),
            attempt_count=2,
            last_error_code="linkedin_rate_limited",
        )
        session.add_all([parked, genuine_retry])
        await session.commit()
        parked_id, retry_id = parked.id, genuine_retry.id
        retry_until = genuine_retry.next_attempt_at

    queued: list = []
    clock = datetime.now(UTC)
    async with factory() as session:
        dispatcher = DispatchService(
            session, settings=settings_off, enqueue=lambda pid: queued.append(pid) or "t"
        )
        # Assert clear semantics first (immune to concurrent live worker claim races).
        cleared = await dispatcher._clear_stale_gate_holds(clock=clock)
        assert cleared >= 1
        parked_after_clear = (
            await session.execute(select(ScheduledPost).where(ScheduledPost.id == parked_id))
        ).scalar_one()
        retry_after_clear = (
            await session.execute(select(ScheduledPost).where(ScheduledPost.id == retry_id))
        ).scalar_one()
        assert parked_after_clear.next_attempt_at is None
        assert retry_after_clear.next_attempt_at == retry_until

        result = await dispatcher.dispatch_due(now=clock)

    assert retry_id not in queued

    async with factory() as session:
        parked_row = (
            await session.execute(select(ScheduledPost).where(ScheduledPost.id == parked_id))
        ).scalar_one()
        retry_row = (
            await session.execute(select(ScheduledPost).where(ScheduledPost.id == retry_id))
        ).scalar_one()
    # Cleared hold: either this dispatcher leased it, or a concurrent dispatcher did.
    assert parked_row.next_attempt_at is None
    assert parked_id in queued or parked_row.dispatch_lease_until is not None
    assert retry_row.next_attempt_at == retry_until
    assert retry_row.dispatch_lease_until is None
    assert result["claimed"] >= 0


@pytest.mark.asyncio
async def test_auth_gate_recheck_is_short_not_seven_days(
    pg_factory: tuple[async_sessionmaker[AsyncSession], Settings],
) -> None:
    assert AUTH_GATE_RECHECK_SECONDS < 3600
    factory, settings = pg_factory
    encryptor = TokenEncryptor.from_settings_value(settings.token_encryption_key)
    linkedin_settings = Settings(
        publish_provider="linkedin",
        enable_real_publishing=True,
        live_publish_require_canary=True,
        live_publish_canary_post_ids=[],
        token_encryption_key=settings.token_encryption_key,
    )
    async with factory() as session:
        user, _raw, connection = await seed_user_session_and_connection(
            session, encryptor=encryptor, subject=f"short-defer-{uuid4()}"
        )
        assert connection is not None
        now = datetime.now(UTC)
        post = _approved_post(
            user_id=user.id,
            connection_id=connection.id,
            content="blocked",
            scheduled_at=now - timedelta(minutes=1),
            approved_by=user.id,
        )
        session.add(post)
        await session.commit()
        post_id = post.id

    async with factory() as session:
        outcome = await run_publish_pipeline(
            session,
            settings=linkedin_settings,
            publisher=FakeLinkedInPublisher(),
            post_id=post_id,
            worker_id="w1",
            celery_task_id="t1",
        )
        assert outcome == "canary_blocked"
        row = (
            await session.execute(select(ScheduledPost).where(ScheduledPost.id == post_id))
        ).scalar_one()
        assert row.next_attempt_at is not None
        delta = (row.next_attempt_at - datetime.now(UTC)).total_seconds()
        assert delta <= AUTH_GATE_RECHECK_SECONDS + 5
        assert delta < 24 * 3600


@pytest.mark.asyncio
async def test_genuine_retry_backoff_preserved(
    pg_factory: tuple[async_sessionmaker[AsyncSession], Settings],
) -> None:
    factory, settings = pg_factory
    encryptor = TokenEncryptor.from_settings_value(settings.token_encryption_key)
    now = datetime.now(UTC)
    retry_at = now + timedelta(hours=2)
    async with factory() as session:
        user, _raw, connection = await seed_user_session_and_connection(
            session, encryptor=encryptor, subject=f"backoff-{uuid4()}"
        )
        assert connection is not None
        post = _approved_post(
            user_id=user.id,
            connection_id=connection.id,
            content="backoff",
            scheduled_at=now - timedelta(hours=1),
            approved_by=user.id,
            next_attempt_at=retry_at,
            attempt_count=1,
            last_error_code="linkedin_rate_limited",
        )
        session.add(post)
        await session.commit()
        post_id = post.id

    queued: list = []
    async with factory() as session:
        await DispatchService(
            session, settings=settings, enqueue=lambda pid: queued.append(pid) or "t"
        ).dispatch_due(now=now)
    assert post_id not in queued

    async with factory() as session:
        row = (
            await session.execute(select(ScheduledPost).where(ScheduledPost.id == post_id))
        ).scalar_one()
    assert row.next_attempt_at == retry_at


@pytest.mark.asyncio
async def test_concurrent_dispatchers_no_double_queue(
    pg_factory: tuple[async_sessionmaker[AsyncSession], Settings],
) -> None:
    factory, settings = pg_factory
    encryptor = TokenEncryptor.from_settings_value(settings.token_encryption_key)
    async with factory() as session:
        user, _raw, connection = await seed_user_session_and_connection(
            session, encryptor=encryptor, subject=f"disp-race-{uuid4()}"
        )
        assert connection is not None
        now = datetime.now(UTC)
        posts = [
            _approved_post(
                user_id=user.id,
                connection_id=connection.id,
                content=f"race-{i}",
                scheduled_at=now - timedelta(minutes=1),
                approved_by=user.id,
            )
            for i in range(4)
        ]
        session.add_all(posts)
        await session.commit()
        post_ids = {p.id for p in posts}

    queues: list[list] = [[], []]

    async def run_dispatcher(idx: int) -> dict[str, int]:
        async with factory() as session:
            return await DispatchService(
                session,
                settings=settings,
                enqueue=lambda pid: queues[idx].append(pid) or f"t-{idx}",
            ).dispatch_due(now=datetime.now(UTC))

    r1, r2 = await asyncio.gather(run_dispatcher(0), run_dispatcher(1))
    combined = queues[0] + queues[1]
    assert len(combined) == len(set(combined))
    assert post_ids.issubset(set(combined))
    assert r1["claimed"] + r2["claimed"] >= 4
