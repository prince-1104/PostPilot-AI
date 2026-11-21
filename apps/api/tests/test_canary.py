"""Phase 4C live-publishing canary safety tests."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import httpx
import pytest
from sqlalchemy import select

from app.models import PublishAttempt, ScheduledPost
from app.models.enums import PostStatus
from app.publishing.authorization import apply_publish_approval
from app.publishing.canary import canary_enforced, is_post_canary_approved
from app.publishing.fake import FakeLinkedInPublisher
from app.publishing.gates import AUTH_GATE_RECHECK_SECONDS
from app.publishing.real import RealLinkedInPublisher
from app.services.publishing.dispatcher import DispatchService
from app.services.publishing.executor import run_publish_pipeline
from app.services.publishing_readiness import PublishingReadinessService
from tests.conftest import seed_user_session_and_connection, session_cookie_header


async def _seed_due(
    db_session,
    token_encryptor,
    *,
    content: str = "canary-body",
    publish_approved: bool = True,
) -> tuple[object, ScheduledPost]:
    user, _raw, connection = await seed_user_session_and_connection(
        db_session, encryptor=token_encryptor, subject=f"canary-{uuid4()}"
    )
    assert connection is not None
    now = datetime.now(UTC)
    post = ScheduledPost(
        id=uuid4(),
        user_id=user.id,
        linkedin_connection_id=connection.id,
        content=content,
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
    if publish_approved:
        apply_publish_approval(post, approved_by=user.id, clock=now)
    db_session.add(post)
    await db_session.commit()
    await db_session.refresh(post)
    return user, post


def test_canary_defaults_block_when_linkedin(settings_factory) -> None:
    settings = settings_factory(
        publish_provider="linkedin",
        enable_real_publishing=True,
    )
    assert canary_enforced(settings) is True
    assert is_post_canary_approved(settings, uuid4()) is False


def test_fake_provider_ignores_canary(settings_factory) -> None:
    settings = settings_factory(publish_provider="fake")
    assert canary_enforced(settings) is False
    assert is_post_canary_approved(settings, uuid4()) is True


def test_real_publishing_disabled_by_default(settings_factory) -> None:
    settings = settings_factory()
    assert settings.publish_provider == "fake"
    assert settings.enable_real_publishing is False
    assert settings.live_publish_require_canary is True


@pytest.mark.asyncio
async def test_unapproved_post_never_calls_real_publisher(
    db_session, settings_factory, token_encryptor
) -> None:
    settings = settings_factory(
        publish_provider="linkedin",
        enable_real_publishing=True,
        live_publish_require_canary=True,
        live_publish_canary_post_ids=[],
    )
    _user, post = await _seed_due(db_session, token_encryptor, publish_approved=True)
    calls = 0

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(201, headers={"x-restli-id": "urn:li:share:1"})

    publisher = RealLinkedInPublisher(
        settings=settings,
        encryptor=token_encryptor,
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    result = await run_publish_pipeline(
        db_session,
        settings=settings,
        publisher=publisher,
        post_id=post.id,
        worker_id="w1",
        celery_task_id="t1",
    )
    assert result == "canary_blocked"
    assert calls == 0
    await db_session.refresh(post)
    assert post.status == PostStatus.SCHEDULED.value
    assert post.linkedin_post_urn is None
    assert post.next_attempt_at is not None
    # Gate holds must be short — never a multi-day park.
    next_at = post.next_attempt_at
    if next_at.tzinfo is None:
        next_at = next_at.replace(tzinfo=UTC)
    delta = (next_at - datetime.now(UTC)).total_seconds()
    assert delta <= AUTH_GATE_RECHECK_SECONDS + 5
    assert delta < 3600


@pytest.mark.asyncio
async def test_approved_canary_reaches_mocked_publisher(
    db_session, settings_factory, token_encryptor
) -> None:
    _user, post = await _seed_due(db_session, token_encryptor, content="approved")
    settings = settings_factory(
        publish_provider="linkedin",
        enable_real_publishing=True,
        live_publish_require_canary=True,
        live_publish_canary_post_ids=[post.id],
    )
    calls = 0

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(
            201, headers={"x-restli-id": "urn:li:share:777666555444"}
        )

    publisher = RealLinkedInPublisher(
        settings=settings,
        encryptor=token_encryptor,
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    result = await run_publish_pipeline(
        db_session,
        settings=settings,
        publisher=publisher,
        post_id=post.id,
        worker_id="w1",
        celery_task_id="t1",
    )
    assert result == PostStatus.PUBLISHED.value
    assert calls == 1
    await db_session.refresh(post)
    assert post.linkedin_post_urn == "urn:li:share:777666555444"


@pytest.mark.asyncio
async def test_dispatcher_skips_non_canary_when_linkedin(
    db_session, settings_factory, token_encryptor
) -> None:
    _user, post = await _seed_due(db_session, token_encryptor)
    settings = settings_factory(
        publish_provider="linkedin",
        enable_real_publishing=True,
        live_publish_require_canary=True,
        live_publish_canary_post_ids=[],
    )
    queued: list = []
    result = await DispatchService(
        db_session, settings=settings, enqueue=lambda pid: queued.append(pid) or "t"
    ).dispatch_due(now=datetime.now(UTC))
    assert result["claimed"] == 0
    assert queued == []
    await db_session.refresh(post)
    assert post.dispatch_lease_until is None


@pytest.mark.asyncio
async def test_old_scheduled_posts_remain_blocked(
    db_session, settings_factory, token_encryptor
) -> None:
    _user, old = await _seed_due(
        db_session, token_encryptor, content="old", publish_approved=False
    )
    _user2, approved = await _seed_due(
        db_session, token_encryptor, content="new", publish_approved=True
    )
    settings = settings_factory(
        publish_provider="linkedin",
        enable_real_publishing=True,
        live_publish_require_canary=True,
        live_publish_canary_post_ids=[approved.id],
    )
    queued: list = []
    await DispatchService(
        db_session, settings=settings, enqueue=lambda pid: queued.append(pid) or "t"
    ).dispatch_due(now=datetime.now(UTC))
    assert queued == [approved.id]
    await db_session.refresh(old)
    assert old.dispatch_lease_until is None


@pytest.mark.asyncio
async def test_fake_provider_still_publishes_without_canary(
    db_session, settings, token_encryptor
) -> None:
    _user, post = await _seed_due(db_session, token_encryptor, content="[[fake:success]]")
    result = await run_publish_pipeline(
        db_session,
        settings=settings,
        publisher=FakeLinkedInPublisher(),
        post_id=post.id,
        worker_id="w1",
        celery_task_id="t1",
    )
    assert result == PostStatus.PUBLISHED.value


@pytest.mark.asyncio
async def test_duplicate_delivery_safe_with_canary(
    db_session, settings_factory, token_encryptor
) -> None:
    _user, post = await _seed_due(db_session, token_encryptor)
    settings = settings_factory(
        publish_provider="linkedin",
        enable_real_publishing=True,
        live_publish_require_canary=True,
        live_publish_canary_post_ids=[post.id],
    )
    calls = 0

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(
            201, headers={"x-restli-id": "urn:li:ugcPost:111"}
        )

    def publisher() -> RealLinkedInPublisher:
        return RealLinkedInPublisher(
            settings=settings,
            encryptor=token_encryptor,
            http_client=httpx.Client(transport=httpx.MockTransport(handler)),
        )

    first = await run_publish_pipeline(
        db_session,
        settings=settings,
        publisher=publisher(),
        post_id=post.id,
        worker_id="a",
        celery_task_id="a",
    )
    second = await run_publish_pipeline(
        db_session,
        settings=settings,
        publisher=publisher(),
        post_id=post.id,
        worker_id="b",
        celery_task_id="b",
    )
    assert first == PostStatus.PUBLISHED.value
    assert second == "skipped"
    assert calls == 1


@pytest.mark.asyncio
async def test_readiness_hides_secrets(
    db_session, settings, token_encryptor, db_client
) -> None:
    user, raw, _conn = await seed_user_session_and_connection(
        db_session, encryptor=token_encryptor, subject=f"ready-{uuid4()}"
    )
    report = await PublishingReadinessService(db_session, settings=settings).diagnose(user)
    blob = report.model_dump_json()
    assert "linkedin-access-token" not in blob
    assert "Bearer" not in blob
    assert report.publishing_verified is False
    assert report.enable_real_publishing is False
    assert report.publish_provider == "fake"

    response = await db_client.get(
        "/api/v1/publishing/readiness",
        headers=session_cookie_header(raw),
    )
    assert response.status_code == 200
    body = response.text
    assert "linkedin-access-token" not in body
    assert "Authorization" not in body
    data = response.json()
    assert "checks" in data
    assert data["publishing_verified"] is False
    assert data["ready_for_test"] is False


@pytest.mark.asyncio
async def test_canary_block_creates_no_publish_attempt_before_claim(
    db_session, settings_factory, token_encryptor
) -> None:
    settings = settings_factory(
        publish_provider="linkedin",
        enable_real_publishing=True,
        live_publish_require_canary=True,
        live_publish_canary_post_ids=[],
    )
    _user, post = await _seed_due(db_session, token_encryptor)
    await run_publish_pipeline(
        db_session,
        settings=settings,
        publisher=FakeLinkedInPublisher(),
        post_id=post.id,
        worker_id="w1",
        celery_task_id="t1",
    )
    attempts = (
        await db_session.execute(
            select(PublishAttempt).where(PublishAttempt.post_id == post.id)
        )
    ).scalars().all()
    assert attempts == []
