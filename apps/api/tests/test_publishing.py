"""Phase 4A publishing engine tests with the deterministic fake provider."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import select

from app.models import PublishAttempt, ScheduledPost
from app.models.enums import AttemptExecutionState, PostStatus
from app.publishing.fake import FakeLinkedInPublisher
from app.publishing.outcomes import OutcomeKind, PublishOutcome
from app.services.publishing.claim import ClaimService
from app.services.publishing.dispatcher import DispatchService
from app.services.publishing.executor import PublishExecutor, run_publish_pipeline
from app.services.publishing.recovery import RecoveryService
from app.services.publishing.retry import compute_retry_at
from tests.conftest import seed_user_session_and_connection


async def _seed_due_post(db_session, token_encryptor, *, content: str, scheduled_offset: timedelta):
    user, _raw, connection = await seed_user_session_and_connection(
        db_session, encryptor=token_encryptor, subject=f"pub-{uuid4()}"
    )
    assert connection is not None
    now = datetime.now(UTC)
    post = ScheduledPost(
        id=uuid4(),
        user_id=user.id,
        linkedin_connection_id=connection.id,
        content=content,
        scheduled_at=now + scheduled_offset,
        timezone="UTC",
        status=PostStatus.SCHEDULED.value,
        idempotency_key=f"idem-{uuid4().hex[:12]}",
        request_fingerprint="abc",
        version=1,
        attempt_count=0,
        created_at=now,
        updated_at=now,
    )
    db_session.add(post)
    await db_session.commit()
    await db_session.refresh(post)
    return user, connection, post


@pytest.mark.asyncio
async def test_dispatcher_skips_future_posts(db_session, settings, token_encryptor) -> None:
    _user, _conn, post = await _seed_due_post(
        db_session, token_encryptor, content="later", scheduled_offset=timedelta(hours=2)
    )
    queued: list = []

    result = await DispatchService(
        db_session, settings=settings, enqueue=lambda pid: queued.append(pid) or "task"
    ).dispatch_due(now=datetime.now(UTC))

    assert result["claimed"] == 0
    assert queued == []
    await db_session.refresh(post)
    assert post.dispatch_lease_until is None


@pytest.mark.asyncio
async def test_dispatcher_claims_due_and_enqueues(db_session, settings, token_encryptor) -> None:
    _user, _conn, post = await _seed_due_post(
        db_session, token_encryptor, content="due", scheduled_offset=timedelta(minutes=-5)
    )
    queued: list = []

    result = await DispatchService(
        db_session, settings=settings, enqueue=lambda pid: queued.append(pid) or "task-1"
    ).dispatch_due(now=datetime.now(UTC))

    assert result["claimed"] == 1
    assert result["queued"] == 1
    assert queued == [post.id]
    await db_session.refresh(post)
    assert post.dispatch_lease_until is not None
    assert post.status == PostStatus.SCHEDULED.value


@pytest.mark.asyncio
async def test_cancel_before_claim_skips_worker(db_session, settings, token_encryptor) -> None:
    _user, _conn, post = await _seed_due_post(
        db_session, token_encryptor, content="cancel-me", scheduled_offset=timedelta(minutes=-1)
    )
    post.status = PostStatus.CANCELLED.value
    await db_session.commit()

    claim = await ClaimService(db_session, settings=settings).claim(
        post_id=post.id, worker_id="w1", celery_task_id="t1"
    )
    assert claim is None


@pytest.mark.asyncio
async def test_successful_fake_publish(db_session, settings, token_encryptor) -> None:
    _user, _conn, post = await _seed_due_post(
        db_session,
        token_encryptor,
        content="hello [[fake:success]]",
        scheduled_offset=timedelta(minutes=-1),
    )
    publisher = FakeLinkedInPublisher()
    outcome = await run_publish_pipeline(
        db_session,
        settings=settings,
        publisher=publisher,
        post_id=post.id,
        worker_id="w1",
        celery_task_id="t1",
    )
    assert outcome == PostStatus.PUBLISHED.value
    await db_session.refresh(post)
    assert post.status == PostStatus.PUBLISHED.value
    assert post.linkedin_post_urn is not None
    assert post.linkedin_post_urn.startswith("urn:li:share:fake-")
    assert post.published_at is not None
    attempts = (
        await db_session.execute(select(PublishAttempt).where(PublishAttempt.post_id == post.id))
    ).scalars().all()
    assert len(attempts) == 1
    assert attempts[0].execution_state == AttemptExecutionState.SUCCEEDED.value


@pytest.mark.asyncio
async def test_rate_limit_schedules_retry(db_session, settings, token_encryptor) -> None:
    _user, _conn, post = await _seed_due_post(
        db_session,
        token_encryptor,
        content="[[fake:rate_limit]]",
        scheduled_offset=timedelta(minutes=-1),
    )
    outcome = await run_publish_pipeline(
        db_session,
        settings=settings,
        publisher=FakeLinkedInPublisher(),
        post_id=post.id,
        worker_id="w1",
        celery_task_id="t1",
    )
    assert outcome == PostStatus.SCHEDULED.value
    await db_session.refresh(post)
    assert post.status == PostStatus.SCHEDULED.value
    assert post.next_attempt_at is not None
    next_at = post.next_attempt_at
    if next_at.tzinfo is None:
        next_at = next_at.replace(tzinfo=UTC)
    assert next_at > datetime.now(UTC)
    assert post.last_error_code == "linkedin_rate_limited"


@pytest.mark.asyncio
async def test_permanent_rejection_fails(db_session, settings, token_encryptor) -> None:
    _user, _conn, post = await _seed_due_post(
        db_session,
        token_encryptor,
        content="[[fake:permanent]]",
        scheduled_offset=timedelta(minutes=-1),
    )
    outcome = await run_publish_pipeline(
        db_session,
        settings=settings,
        publisher=FakeLinkedInPublisher(),
        post_id=post.id,
        worker_id="w1",
        celery_task_id="t1",
    )
    assert outcome == PostStatus.FAILED.value
    await db_session.refresh(post)
    assert post.status == PostStatus.FAILED.value


@pytest.mark.asyncio
async def test_ambiguous_requires_review_no_auto_retry(
    db_session, settings, token_encryptor
) -> None:
    _user, _conn, post = await _seed_due_post(
        db_session,
        token_encryptor,
        content="[[fake:ambiguous]]",
        scheduled_offset=timedelta(minutes=-1),
    )
    outcome = await run_publish_pipeline(
        db_session,
        settings=settings,
        publisher=FakeLinkedInPublisher(),
        post_id=post.id,
        worker_id="w1",
        celery_task_id="t1",
    )
    assert outcome == PostStatus.REQUIRES_REVIEW.value
    await db_session.refresh(post)
    assert post.status == PostStatus.REQUIRES_REVIEW.value
    assert post.next_attempt_at is None

    # Duplicate Celery delivery must not republish.
    again = await run_publish_pipeline(
        db_session,
        settings=settings,
        publisher=FakeLinkedInPublisher(),
        post_id=post.id,
        worker_id="w2",
        celery_task_id="t2",
    )
    assert again == "skipped"


@pytest.mark.asyncio
async def test_pre_network_failure_retries(db_session, settings, token_encryptor) -> None:
    _user, _conn, post = await _seed_due_post(
        db_session,
        token_encryptor,
        content="[[fake:pre_network]]",
        scheduled_offset=timedelta(minutes=-1),
    )
    outcome = await run_publish_pipeline(
        db_session,
        settings=settings,
        publisher=FakeLinkedInPublisher(),
        post_id=post.id,
        worker_id="w1",
        celery_task_id="t1",
    )
    assert outcome == PostStatus.SCHEDULED.value
    await db_session.refresh(post)
    assert post.status == PostStatus.SCHEDULED.value


@pytest.mark.asyncio
async def test_stale_worker_fenced_out(db_session, settings, token_encryptor) -> None:
    _user, _conn, post = await _seed_due_post(
        db_session, token_encryptor, content="fence", scheduled_offset=timedelta(minutes=-1)
    )
    claim = await ClaimService(db_session, settings=settings).claim(
        post_id=post.id, worker_id="w1", celery_task_id="t1"
    )
    assert claim is not None
    # Simulate a newer claim fencing token.
    await db_session.refresh(post)
    post.current_attempt_id = uuid4()
    await db_session.commit()

    executor = PublishExecutor(
        db_session, settings=settings, publisher=FakeLinkedInPublisher()
    )
    result = await executor.apply_outcome(
        claim=claim,
        outcome=PublishOutcome(
            kind=OutcomeKind.SUCCESS,
            submission_started=True,
            provider_post_urn="urn:li:share:fake-stale",
            simulated=True,
        ),
    )
    assert result == "fenced_out"
    await db_session.refresh(post)
    assert post.status == PostStatus.PROCESSING.value
    assert post.linkedin_post_urn is None


@pytest.mark.asyncio
async def test_recovery_pre_submission_requeues(db_session, settings, token_encryptor) -> None:
    _user, _conn, post = await _seed_due_post(
        db_session, token_encryptor, content="recover", scheduled_offset=timedelta(minutes=-1)
    )
    claim = await ClaimService(db_session, settings=settings).claim(
        post_id=post.id, worker_id="w1", celery_task_id="t1"
    )
    assert claim is not None
    await db_session.refresh(post)
    post.processing_lease_until = datetime.now(UTC) - timedelta(seconds=5)
    await db_session.commit()

    result = await RecoveryService(db_session, settings=settings).recover_expired_leases(
        now=datetime.now(UTC)
    )
    assert result["requeued"] == 1
    await db_session.refresh(post)
    assert post.status == PostStatus.SCHEDULED.value


@pytest.mark.asyncio
async def test_recovery_after_submitting_requires_review(
    db_session, settings, token_encryptor
) -> None:
    _user, _conn, post = await _seed_due_post(
        db_session, token_encryptor, content="ambig", scheduled_offset=timedelta(minutes=-1)
    )
    claim = await ClaimService(db_session, settings=settings).claim(
        post_id=post.id, worker_id="w1", celery_task_id="t1"
    )
    assert claim is not None
    executor = PublishExecutor(
        db_session, settings=settings, publisher=FakeLinkedInPublisher()
    )
    assert await executor.mark_submitting(claim=claim) is True
    await db_session.refresh(post)
    post.processing_lease_until = datetime.now(UTC) - timedelta(seconds=5)
    await db_session.commit()

    result = await RecoveryService(db_session, settings=settings).recover_expired_leases(
        now=datetime.now(UTC)
    )
    assert result["requires_review"] == 1
    await db_session.refresh(post)
    assert post.status == PostStatus.REQUIRES_REVIEW.value


@pytest.mark.asyncio
async def test_published_never_redpatched(db_session, settings, token_encryptor) -> None:
    _user, _conn, post = await _seed_due_post(
        db_session, token_encryptor, content="done", scheduled_offset=timedelta(minutes=-1)
    )
    post.status = PostStatus.PUBLISHED.value
    post.published_at = datetime.now(UTC)
    post.linkedin_post_urn = "urn:li:share:fake-done"
    await db_session.commit()

    claim = await ClaimService(db_session, settings=settings).claim(
        post_id=post.id, worker_id="w1", celery_task_id="t1"
    )
    assert claim is None


def test_retry_backoff_honors_retry_after(settings) -> None:
    clock = datetime(2026, 1, 1, tzinfo=UTC)
    next_at = compute_retry_at(
        settings=settings, attempt_number=1, clock=clock, retry_after_seconds=120
    )
    assert (next_at - clock).total_seconds() >= 120


@pytest.mark.asyncio
async def test_attempts_api_user_isolation(
    db_client, db_session, settings, token_encryptor
) -> None:
    from tests.conftest import ALLOWED_ORIGIN

    _user_a, raw_a, conn_a = await seed_user_session_and_connection(
        db_session, encryptor=token_encryptor, subject=f"a-{uuid4()}"
    )
    _user_b, raw_b, _conn_b = await seed_user_session_and_connection(
        db_session, encryptor=token_encryptor, subject=f"b-{uuid4()}"
    )
    assert conn_a is not None
    when = datetime.now(UTC) + timedelta(hours=2)
    create = await db_client.post(
        "/api/v1/posts",
        headers={
            "Cookie": f"postpilot_session={raw_a}",
            "Origin": ALLOWED_ORIGIN,
            "Idempotency-Key": f"idem-{uuid4().hex[:12]}",
        },
        json={
            "content": "isolation",
            "scheduled_at": when.isoformat(),
            "timezone": "UTC",
            "linkedin_connection_id": str(conn_a.id),
        },
    )
    assert create.status_code == 201
    post_id = create.json()["id"]

    own = await db_client.get(
        f"/api/v1/posts/{post_id}/attempts",
        headers={"Cookie": f"postpilot_session={raw_a}"},
    )
    assert own.status_code == 200
    assert own.json()["items"] == []

    other = await db_client.get(
        f"/api/v1/posts/{post_id}/attempts",
        headers={"Cookie": f"postpilot_session={raw_b}"},
    )
    assert other.status_code == 404


@pytest.mark.asyncio
async def test_retry_exhaustion_marks_failed(
    db_session, settings_factory, token_encryptor
) -> None:
    settings = settings_factory(publish_retry_max_attempts=1)
    _user, _conn, post = await _seed_due_post(
        db_session,
        token_encryptor,
        content="[[fake:rate_limit]]",
        scheduled_offset=timedelta(minutes=-1),
    )
    outcome = await run_publish_pipeline(
        db_session,
        settings=settings,
        publisher=FakeLinkedInPublisher(),
        post_id=post.id,
        worker_id="w1",
        celery_task_id="t1",
    )
    assert outcome == PostStatus.FAILED.value
    await db_session.refresh(post)
    assert post.status == PostStatus.FAILED.value
