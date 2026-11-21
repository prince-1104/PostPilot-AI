"""Phase 4B RealLinkedInPublisher tests — HTTPX mocked, never hits LinkedIn."""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import httpx
import pytest
from pydantic import ValidationError

from app.core.security import TokenEncryptor
from app.models import LinkedInConnection, ScheduledPost
from app.models.enums import ConnectionStatus, PostStatus
from app.publishing.outcomes import OutcomeKind, PublishExecutionContext
from app.publishing.person_urn import (
    PersonUrnError,
    linkedin_permalink_for_post_urn,
    person_urn_from_oidc_subject,
    validate_post_urn,
)
from app.publishing.real import RealLinkedInPublisher
from app.services.publishing.claim import ClaimService
from app.services.publishing.executor import run_publish_pipeline
from tests.conftest import seed_user_session_and_connection, stamp_publish_approval


def _ctx() -> PublishExecutionContext:
    return PublishExecutionContext(
        post_id=str(uuid4()),
        attempt_id=str(uuid4()),
        fencing_token=str(uuid4()),
        attempt_number=1,
        worker_id="test-worker",
        celery_task_id="task-1",
    )


def _connection(
    *,
    encryptor: TokenEncryptor,
    subject: str = "abc123OIDC",
    scopes: str = "openid profile email w_member_social",
    expires_in_hours: int = 24,
    status: str = ConnectionStatus.CONNECTED.value,
    user_id=None,
) -> LinkedInConnection:
    return LinkedInConnection(
        id=uuid4(),
        user_id=user_id or uuid4(),
        provider_subject=subject,
        encrypted_access_token=encryptor.encrypt("test-access-token"),
        token_expires_at=datetime.now(UTC) + timedelta(hours=expires_in_hours),
        granted_scopes=scopes,
        connection_status=status,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )


def _publisher(settings_factory, encryptor: TokenEncryptor, transport: httpx.MockTransport):
    settings = settings_factory(
        publish_provider="linkedin",
        enable_real_publishing=True,
        live_publish_require_canary=False,
        linkedin_api_version="202611",
    )
    client = httpx.Client(transport=transport, timeout=5.0)
    return RealLinkedInPublisher(settings=settings, encryptor=encryptor, http_client=client)


def test_person_urn_from_oidc_sub() -> None:
    assert person_urn_from_oidc_subject("abc123") == "urn:li:person:abc123"
    with pytest.raises(PersonUrnError):
        person_urn_from_oidc_subject("urn:li:organization:9")


def test_validate_and_permalink() -> None:
    urn = validate_post_urn("urn:li:share:6844785523593134080")
    assert linkedin_permalink_for_post_urn(urn)
    with pytest.raises(ValueError, match="valid post URN"):
        validate_post_urn("urn:li:share:fake-not-digits")


def test_success_201_with_restli_id(settings_factory, encryption_key_b64) -> None:
    encryptor = TokenEncryptor.from_settings_value(encryption_key_b64)
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["headers"] = {k.lower(): v for k, v in request.headers.items()}
        captured["body"] = json.loads(request.content.decode())
        return httpx.Response(
            201,
            headers={"x-restli-id": "urn:li:share:6844785523593134080"},
        )

    pub = _publisher(settings_factory, encryptor, httpx.MockTransport(handler))
    conn = _connection(encryptor=encryptor)
    outcome = pub.publish_text_post(
        connection=conn, content="Hello LinkedIn", execution_context=_ctx()
    )
    assert outcome.kind == OutcomeKind.SUCCESS
    assert outcome.provider_post_urn == "urn:li:share:6844785523593134080"
    assert outcome.simulated is False
    assert captured["url"] == "https://api.linkedin.com/rest/posts"
    assert captured["headers"]["linkedin-version"] == "202611"
    assert captured["headers"]["x-restli-protocol-version"] == "2.0.0"
    assert captured["headers"]["authorization"] == "Bearer test-access-token"
    assert captured["body"]["author"] == "urn:li:person:abc123OIDC"
    assert captured["body"]["commentary"] == "Hello LinkedIn"
    assert captured["body"]["visibility"] == "PUBLIC"
    assert captured["body"]["lifecycleState"] == "PUBLISHED"
    assert captured["body"]["distribution"]["feedDistribution"] == "MAIN_FEED"
    assert captured["body"]["distribution"]["targetEntities"] == []
    assert captured["body"]["isReshareDisabledByAuthor"] is False
    assert pub.requests_made[0]["path"] == "/rest/posts"


def test_201_missing_urn_requires_review_outcome(settings_factory, encryption_key_b64) -> None:
    encryptor = TokenEncryptor.from_settings_value(encryption_key_b64)

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(201)

    pub = _publisher(settings_factory, encryptor, httpx.MockTransport(handler))
    outcome = pub.publish_text_post(
        connection=_connection(encryptor=encryptor),
        content="x",
        execution_context=_ctx(),
    )
    assert outcome.kind == OutcomeKind.AMBIGUOUS
    assert outcome.sanitized_error_code == "linkedin_201_missing_post_urn"


def test_201_malformed_urn(settings_factory, encryption_key_b64) -> None:
    encryptor = TokenEncryptor.from_settings_value(encryption_key_b64)

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(201, headers={"x-restli-id": "urn:li:organization:1"})

    pub = _publisher(settings_factory, encryptor, httpx.MockTransport(handler))
    outcome = pub.publish_text_post(
        connection=_connection(encryptor=encryptor),
        content="x",
        execution_context=_ctx(),
    )
    assert outcome.kind == OutcomeKind.AMBIGUOUS
    assert outcome.sanitized_error_code == "linkedin_201_malformed_post_urn"


def test_token_expired_preflight(settings_factory, encryption_key_b64) -> None:
    encryptor = TokenEncryptor.from_settings_value(encryption_key_b64)
    calls = 0

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(500)

    pub = _publisher(settings_factory, encryptor, httpx.MockTransport(handler))
    outcome = pub.publish_text_post(
        connection=_connection(encryptor=encryptor, expires_in_hours=-1),
        content="x",
        execution_context=_ctx(),
    )
    assert outcome.kind == OutcomeKind.CONNECTION_EXPIRED
    assert outcome.sanitized_error_code == "linkedin_token_expired"
    assert calls == 0


def test_missing_scope_preflight(settings_factory, encryption_key_b64) -> None:
    encryptor = TokenEncryptor.from_settings_value(encryption_key_b64)
    pub = _publisher(
        settings_factory, encryptor, httpx.MockTransport(lambda _r: httpx.Response(500))
    )
    outcome = pub.publish_text_post(
        connection=_connection(encryptor=encryptor, scopes="openid profile email"),
        content="x",
        execution_context=_ctx(),
    )
    assert outcome.kind == OutcomeKind.PERMANENT
    assert outcome.sanitized_error_code == "missing_w_member_social"


@pytest.mark.parametrize(
    ("status", "kind", "code"),
    [
        (400, OutcomeKind.PERMANENT, "linkedin_validation_rejected"),
        (401, OutcomeKind.CONNECTION_EXPIRED, "linkedin_unauthorized"),
        (403, OutcomeKind.PERMANENT, "linkedin_forbidden"),
        (500, OutcomeKind.AMBIGUOUS, "linkedin_server_error"),
        (200, OutcomeKind.AMBIGUOUS, "linkedin_unexpected_response"),
    ],
)
def test_http_error_classification(
    settings_factory, encryption_key_b64, status, kind, code
) -> None:
    encryptor = TokenEncryptor.from_settings_value(encryption_key_b64)
    pub = _publisher(
        settings_factory,
        encryptor,
        httpx.MockTransport(lambda _r: httpx.Response(status)),
    )
    outcome = pub.publish_text_post(
        connection=_connection(encryptor=encryptor),
        content="x",
        execution_context=_ctx(),
    )
    assert outcome.kind == kind
    assert outcome.sanitized_error_code == code


def test_429_honors_retry_after(settings_factory, encryption_key_b64) -> None:
    encryptor = TokenEncryptor.from_settings_value(encryption_key_b64)
    pub = _publisher(
        settings_factory,
        encryptor,
        httpx.MockTransport(
            lambda _r: httpx.Response(429, headers={"Retry-After": "90"})
        ),
    )
    outcome = pub.publish_text_post(
        connection=_connection(encryptor=encryptor),
        content="x",
        execution_context=_ctx(),
    )
    assert outcome.kind == OutcomeKind.RETRYABLE
    assert outcome.retry_after_seconds == 90


def test_timeout_after_submission(settings_factory, encryption_key_b64) -> None:
    encryptor = TokenEncryptor.from_settings_value(encryption_key_b64)

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("slow", request=request)

    pub = _publisher(settings_factory, encryptor, httpx.MockTransport(handler))
    outcome = pub.publish_text_post(
        connection=_connection(encryptor=encryptor),
        content="x",
        execution_context=_ctx(),
    )
    assert outcome.kind == OutcomeKind.AMBIGUOUS
    assert outcome.submission_started is True
    assert outcome.sanitized_error_code == "linkedin_publish_timeout"


def test_connection_interruption(settings_factory, encryption_key_b64) -> None:
    encryptor = TokenEncryptor.from_settings_value(encryption_key_b64)

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("reset", request=request)

    pub = _publisher(settings_factory, encryptor, httpx.MockTransport(handler))
    outcome = pub.publish_text_post(
        connection=_connection(encryptor=encryptor),
        content="x",
        execution_context=_ctx(),
    )
    assert outcome.kind == OutcomeKind.AMBIGUOUS
    assert outcome.sanitized_error_code == "linkedin_publish_transport_error"


def test_no_automatic_http_post_retry(settings_factory, encryption_key_b64) -> None:
    encryptor = TokenEncryptor.from_settings_value(encryption_key_b64)
    calls = 0

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(500)

    pub = _publisher(settings_factory, encryptor, httpx.MockTransport(handler))
    pub.publish_text_post(
        connection=_connection(encryptor=encryptor),
        content="x",
        execution_context=_ctx(),
    )
    assert calls == 1


def test_linkedin_provider_requires_enable_flag(settings_factory) -> None:
    with pytest.raises(ValidationError, match="ENABLE_REAL_PUBLISHING"):
        settings_factory(publish_provider="linkedin", enable_real_publishing=False)


def test_secrets_never_logged(
    settings_factory, encryption_key_b64, caplog: pytest.LogCaptureFixture
) -> None:
    encryptor = TokenEncryptor.from_settings_value(encryption_key_b64)

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            201, headers={"x-restli-id": "urn:li:share:111222333444"}
        )

    pub = _publisher(settings_factory, encryptor, httpx.MockTransport(handler))
    with caplog.at_level(logging.DEBUG):
        pub.publish_text_post(
            connection=_connection(encryptor=encryptor),
            content="secret-post",
            execution_context=_ctx(),
        )
    blob = " ".join(record.getMessage() for record in caplog.records)
    assert "test-access-token" not in blob
    assert "Bearer " not in blob


@pytest.mark.asyncio
async def test_wrong_connection_ownership_fails_claim(
    db_session, settings, token_encryptor
) -> None:
    user, _raw, connection = await seed_user_session_and_connection(
        db_session, encryptor=token_encryptor, subject=f"owner-{uuid4()}"
    )
    other, _raw2, _other_conn = await seed_user_session_and_connection(
        db_session, encryptor=token_encryptor, subject=f"other-{uuid4()}"
    )
    assert connection is not None
    now = datetime.now(UTC)
    post = ScheduledPost(
        id=uuid4(),
        user_id=other.id,
        linkedin_connection_id=connection.id,
        content="stolen-conn",
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

    claim = await ClaimService(db_session, settings=settings).claim(
        post_id=post.id, worker_id="w1", celery_task_id="t1"
    )
    assert claim is None
    await db_session.refresh(post)
    assert post.status == PostStatus.FAILED.value
    assert post.last_error_code == "connection_missing"
    assert user.id != other.id


@pytest.mark.asyncio
async def test_real_success_persists_urn(
    db_session, settings_factory, token_encryptor
) -> None:
    settings = settings_factory(
        publish_provider="linkedin",
        enable_real_publishing=True,
        live_publish_require_canary=False,
    )
    _user, _raw, connection = await seed_user_session_and_connection(
        db_session, encryptor=token_encryptor, subject=f"real-{uuid4()}"
    )
    assert connection is not None
    now = datetime.now(UTC)
    post = ScheduledPost(
        id=uuid4(),
        user_id=_user.id,
        linkedin_connection_id=connection.id,
        content="live-shaped",
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
    stamp_publish_approval(post, approved_by=_user.id, clock=now)
    db_session.add(post)
    await db_session.commit()

    calls = 0

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(
            201, headers={"x-restli-id": "urn:li:ugcPost:999888777666555"}
        )

    publisher = RealLinkedInPublisher(
        settings=settings,
        encryptor=token_encryptor,
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
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
    assert post.linkedin_post_urn == "urn:li:ugcPost:999888777666555"
    assert not post.linkedin_post_urn.startswith("urn:li:share:fake-")
    assert calls == 1

    # Duplicate delivery must not call LinkedIn again.
    again = await run_publish_pipeline(
        db_session,
        settings=settings,
        publisher=publisher,
        post_id=post.id,
        worker_id="w2",
        celery_task_id="t2",
    )
    assert again == "skipped"
    assert calls == 1


@pytest.mark.asyncio
async def test_ambiguous_never_auto_republished(
    db_session, settings_factory, token_encryptor
) -> None:
    settings = settings_factory(
        publish_provider="linkedin",
        enable_real_publishing=True,
        live_publish_require_canary=False,
    )
    _user, _raw, connection = await seed_user_session_and_connection(
        db_session, encryptor=token_encryptor, subject=f"amb-{uuid4()}"
    )
    assert connection is not None
    now = datetime.now(UTC)
    post = ScheduledPost(
        id=uuid4(),
        user_id=_user.id,
        linkedin_connection_id=connection.id,
        content="timeout-case",
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
    stamp_publish_approval(post, approved_by=_user.id, clock=now)
    db_session.add(post)
    await db_session.commit()

    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        raise httpx.ReadTimeout("after write", request=request)

    publisher = RealLinkedInPublisher(
        settings=settings,
        encryptor=token_encryptor,
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    outcome = await run_publish_pipeline(
        db_session,
        settings=settings,
        publisher=publisher,
        post_id=post.id,
        worker_id="w1",
        celery_task_id="t1",
    )
    assert outcome == PostStatus.REQUIRES_REVIEW.value
    assert calls == 1

    again = await run_publish_pipeline(
        db_session,
        settings=settings,
        publisher=publisher,
        post_id=post.id,
        worker_id="w2",
        celery_task_id="t2",
    )
    assert again == "skipped"
    assert calls == 1


@pytest.mark.asyncio
async def test_fake_provider_still_works(db_session, settings, token_encryptor) -> None:
    from app.publishing.fake import FakeLinkedInPublisher

    _user, _raw, connection = await seed_user_session_and_connection(
        db_session, encryptor=token_encryptor, subject=f"fake-{uuid4()}"
    )
    assert connection is not None
    now = datetime.now(UTC)
    post = ScheduledPost(
        id=uuid4(),
        user_id=_user.id,
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
    db_session.add(post)
    await db_session.commit()

    outcome = await run_publish_pipeline(
        db_session,
        settings=settings,
        publisher=FakeLinkedInPublisher(),
        post_id=post.id,
        worker_id="w1",
        celery_task_id="t1",
    )
    assert outcome == PostStatus.PUBLISHED.value
    await db_session.refresh(post)
    assert post.linkedin_post_urn is not None
    assert post.linkedin_post_urn.startswith("urn:li:share:fake-")
