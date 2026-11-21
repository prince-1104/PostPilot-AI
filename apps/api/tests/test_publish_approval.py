"""Durable per-post publishing approval tests."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import httpx
import pytest

from app.models import ScheduledPost
from app.models.enums import PostStatus
from app.publishing.authorization import (
    apply_publish_approval,
    db_approval_required,
    is_db_publish_approved,
    is_post_authorized_to_publish,
)
from app.publishing.real import RealLinkedInPublisher
from app.services.publishing.dispatcher import DispatchService
from app.services.publishing.executor import run_publish_pipeline
from tests.conftest import (
    ALLOWED_ORIGIN,
    seed_user_session_and_connection,
    session_cookie_header,
    stamp_publish_approval,
)


def _auth_headers(raw: str, *, idempotency: str) -> dict[str, str]:
    return {
        **session_cookie_header(raw),
        "Origin": ALLOWED_ORIGIN,
        "Idempotency-Key": idempotency,
    }


@pytest.mark.asyncio
async def test_create_without_confirm_rejected(db_client, db_session, token_encryptor) -> None:
    _user, raw, connection = await seed_user_session_and_connection(
        db_session, encryptor=token_encryptor
    )
    when = datetime.now(UTC) + timedelta(hours=2)
    response = await db_client.post(
        "/api/v1/posts",
        headers=_auth_headers(raw, idempotency="idem-noconfirm-01"),
        json={
            "content": "No confirm",
            "scheduled_at": when.isoformat(),
            "timezone": "UTC",
            "confirm_publish": False,
            "linkedin_connection_id": str(connection.id),
        },
    )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_unapproved_never_publishes_on_linkedin(
    db_session, settings_factory, token_encryptor
) -> None:
    settings = settings_factory(
        publish_provider="linkedin",
        enable_real_publishing=True,
        live_publish_require_canary=False,
    )
    assert db_approval_required(settings) is True
    user, _raw, connection = await seed_user_session_and_connection(
        db_session, encryptor=token_encryptor, subject=f"unapp-{uuid4()}"
    )
    now = datetime.now(UTC)
    post = ScheduledPost(
        id=uuid4(),
        user_id=user.id,
        linkedin_connection_id=connection.id,
        content="no-approval",
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
    db_session.add(post)
    await db_session.commit()
    assert is_db_publish_approved(post) is False

    calls = 0

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(201, headers={"x-restli-id": "urn:li:share:1"})

    result = await run_publish_pipeline(
        db_session,
        settings=settings,
        publisher=RealLinkedInPublisher(
            settings=settings,
            encryptor=token_encryptor,
            http_client=httpx.Client(transport=httpx.MockTransport(handler)),
        ),
        post_id=post.id,
        worker_id="w1",
        celery_task_id="t1",
    )
    assert result == "publish_approval_required"
    assert calls == 0


@pytest.mark.asyncio
async def test_approved_post_eligible_when_due_without_canary(
    db_session, settings_factory, token_encryptor
) -> None:
    settings = settings_factory(
        publish_provider="linkedin",
        enable_real_publishing=True,
        live_publish_require_canary=False,
    )
    user, _raw, connection = await seed_user_session_and_connection(
        db_session, encryptor=token_encryptor, subject=f"ok-{uuid4()}"
    )
    now = datetime.now(UTC)
    post = ScheduledPost(
        id=uuid4(),
        user_id=user.id,
        linkedin_connection_id=connection.id,
        content="approved-body",
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
    stamp_publish_approval(post, approved_by=user.id, clock=now)
    db_session.add(post)
    await db_session.commit()

    queued: list = []
    await DispatchService(
        db_session, settings=settings, enqueue=lambda pid: queued.append(pid) or "t"
    ).dispatch_due(now=datetime.now(UTC))
    assert queued == [post.id]

    calls = 0

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(201, headers={"x-restli-id": "urn:li:share:4242"})

    result = await run_publish_pipeline(
        db_session,
        settings=settings,
        publisher=RealLinkedInPublisher(
            settings=settings,
            encryptor=token_encryptor,
            http_client=httpx.Client(transport=httpx.MockTransport(handler)),
        ),
        post_id=post.id,
        worker_id="w1",
        celery_task_id="t1",
    )
    assert result == PostStatus.PUBLISHED.value
    assert calls == 1


@pytest.mark.asyncio
async def test_approving_one_post_does_not_approve_others(
    db_session, settings_factory, token_encryptor
) -> None:
    settings = settings_factory(
        publish_provider="linkedin",
        enable_real_publishing=True,
        live_publish_require_canary=False,
    )
    user, _raw, connection = await seed_user_session_and_connection(
        db_session, encryptor=token_encryptor, subject=f"multi-{uuid4()}"
    )
    now = datetime.now(UTC)
    posts: list[ScheduledPost] = []
    for label in ("a", "b"):
        post = ScheduledPost(
            id=uuid4(),
            user_id=user.id,
            linkedin_connection_id=connection.id,
            content=label,
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
        posts.append(post)
        db_session.add(post)
    apply_publish_approval(posts[0], approved_by=user.id, clock=now)
    await db_session.commit()

    queued: list = []
    await DispatchService(
        db_session, settings=settings, enqueue=lambda pid: queued.append(pid) or "t"
    ).dispatch_due(now=datetime.now(UTC))
    assert queued == [posts[0].id]


@pytest.mark.asyncio
async def test_cannot_approve_another_users_post(
    db_client, db_session, token_encryptor
) -> None:
    owner, _raw_a, connection = await seed_user_session_and_connection(
        db_session, encryptor=token_encryptor, subject=f"owner-{uuid4()}"
    )
    _intruder, raw_b, _ = await seed_user_session_and_connection(
        db_session, encryptor=token_encryptor, subject=f"intruder-{uuid4()}"
    )
    now = datetime.now(UTC)
    post = ScheduledPost(
        id=uuid4(),
        user_id=owner.id,
        linkedin_connection_id=connection.id,
        content="private",
        scheduled_at=now + timedelta(hours=2),
        timezone="UTC",
        status=PostStatus.SCHEDULED.value,
        idempotency_key=f"idem-{uuid4().hex[:12]}",
        request_fingerprint="fp",
        version=1,
        attempt_count=0,
        created_at=now,
        updated_at=now,
    )
    db_session.add(post)
    await db_session.commit()

    response = await db_client.post(
        f"/api/v1/posts/{post.id}/approve",
        headers={**session_cookie_header(raw_b), "Origin": ALLOWED_ORIGIN},
        json={"expected_version": 1, "confirm_publish": True},
    )
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_edit_without_confirm_rejected_and_keeps_prior_approval_intact_until_edit(
    db_client, db_session, token_encryptor
) -> None:
    _user, raw, connection = await seed_user_session_and_connection(
        db_session, encryptor=token_encryptor
    )
    when = datetime.now(UTC) + timedelta(hours=3)
    create = await db_client.post(
        "/api/v1/posts",
        headers=_auth_headers(raw, idempotency="idem-edit-approve-01"),
        json={
            "content": "Original",
            "scheduled_at": when.isoformat(),
            "timezone": "UTC",
            "confirm_publish": True,
            "linkedin_connection_id": str(connection.id),
        },
    )
    assert create.status_code == 201
    post = create.json()
    denied = await db_client.patch(
        f"/api/v1/posts/{post['id']}",
        headers={**session_cookie_header(raw), "Origin": ALLOWED_ORIGIN},
        json={"expected_version": post["version"], "content": "Changed"},
    )
    assert denied.status_code == 422

    ok = await db_client.patch(
        f"/api/v1/posts/{post['id']}",
        headers={**session_cookie_header(raw), "Origin": ALLOWED_ORIGIN},
        json={
            "expected_version": post["version"],
            "content": "Changed",
            "confirm_publish": True,
        },
    )
    assert ok.status_code == 200, ok.text
    body = ok.json()
    assert body["content"] == "Changed"
    assert body["publish_approved"] is True


@pytest.mark.asyncio
async def test_canary_still_required_when_db_approved(
    db_session, settings_factory, token_encryptor
) -> None:
    settings = settings_factory(
        publish_provider="linkedin",
        enable_real_publishing=True,
        live_publish_require_canary=True,
        live_publish_canary_post_ids=[],
    )
    user, _raw, connection = await seed_user_session_and_connection(
        db_session, encryptor=token_encryptor, subject=f"can-{uuid4()}"
    )
    now = datetime.now(UTC)
    post = ScheduledPost(
        id=uuid4(),
        user_id=user.id,
        linkedin_connection_id=connection.id,
        content="db-ok-canary-no",
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
    stamp_publish_approval(post, approved_by=user.id, clock=now)
    db_session.add(post)
    await db_session.commit()
    assert is_post_authorized_to_publish(settings, post) is False

    queued: list = []
    await DispatchService(
        db_session, settings=settings, enqueue=lambda pid: queued.append(pid) or "t"
    ).dispatch_due(now=datetime.now(UTC))
    assert queued == []
