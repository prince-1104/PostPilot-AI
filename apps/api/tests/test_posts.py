"""Scheduled post API behaviour."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import select

from app.models import ScheduledPost
from app.models.enums import PostStatus
from tests.conftest import (
    ALLOWED_ORIGIN,
    seed_user_session_and_connection,
    session_cookie_header,
)


def _aware(*, hours: int = 2, tz_name: str = "UTC") -> tuple[datetime, str]:
    tz = ZoneInfo(tz_name)
    when = datetime.now(tz) + timedelta(hours=hours)
    return when, tz_name


def _auth_headers(raw: str, *, idempotency: str | None = None) -> dict[str, str]:
    headers = {**session_cookie_header(raw), "Origin": ALLOWED_ORIGIN}
    if idempotency is not None:
        headers["Idempotency-Key"] = idempotency
    return headers


@pytest.mark.asyncio
async def test_create_requires_auth(db_client) -> None:
    when, tz = _aware()
    response = await db_client.post(
        "/api/v1/posts",
        headers={"Idempotency-Key": "idem-unauth-01", "Origin": ALLOWED_ORIGIN},
        json={
            "content": "Hello",
            "scheduled_at": when.isoformat(),
            "timezone": tz,
            "confirm_publish": True,
            "linkedin_connection_id": str(uuid4()),
        },
    )
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_create_and_get_post(
    db_client, db_session, token_encryptor, settings
) -> None:
    _user, raw, connection = await seed_user_session_and_connection(
        db_session, encryptor=token_encryptor
    )
    assert connection is not None
    when, tz = _aware(hours=3, tz_name="Asia/Kolkata")
    create = await db_client.post(
        "/api/v1/posts",
        headers=_auth_headers(raw, idempotency="idem-create-01"),
        json={
            "content": "Shipping Phase 3",
            "scheduled_at": when.isoformat(),
            "timezone": tz,
            "confirm_publish": True,
            "linkedin_connection_id": str(connection.id),
        },
    )
    assert create.status_code == 201, create.text
    body = create.json()
    assert body["content"] == "Shipping Phase 3"
    assert body["status"] == "scheduled"
    assert body["version"] == 1
    assert body["timezone"] == "Asia/Kolkata"
    assert body["publish_approved"] is True
    assert body["publish_approved_by"] == str(_user.id)
    assert "token" not in body

    fetched = await db_client.get(
        f"/api/v1/posts/{body['id']}", headers=session_cookie_header(raw)
    )
    assert fetched.status_code == 200
    assert fetched.json()["id"] == body["id"]


@pytest.mark.asyncio
async def test_missing_connection_and_wrong_owner(
    db_client, db_session, token_encryptor
) -> None:
    _user, raw, _conn = await seed_user_session_and_connection(
        db_session, encryptor=token_encryptor, subject="owner-a"
    )
    _other, _raw_b, other_conn = await seed_user_session_and_connection(
        db_session, encryptor=token_encryptor, subject="owner-b"
    )
    when, tz = _aware()
    missing = await db_client.post(
        "/api/v1/posts",
        headers=_auth_headers(raw, idempotency="idem-miss-01"),
        json={
            "content": "Nope",
            "scheduled_at": when.isoformat(),
            "timezone": tz,
            "confirm_publish": True,
            "linkedin_connection_id": str(uuid4()),
        },
    )
    assert missing.status_code == 403

    stolen = await db_client.post(
        "/api/v1/posts",
        headers=_auth_headers(raw, idempotency="idem-steal-01"),
        json={
            "content": "Nope",
            "scheduled_at": when.isoformat(),
            "timezone": tz,
            "confirm_publish": True,
            "linkedin_connection_id": str(other_conn.id),
        },
    )
    assert stolen.status_code == 403


@pytest.mark.asyncio
async def test_missing_posting_permission(db_client, db_session, token_encryptor) -> None:
    _user, raw, connection = await seed_user_session_and_connection(
        db_session,
        encryptor=token_encryptor,
        granted_scopes="openid profile email",
    )
    when, tz = _aware()
    response = await db_client.post(
        "/api/v1/posts",
        headers=_auth_headers(raw, idempotency="idem-scope-01"),
        json={
            "content": "No publish scope",
            "scheduled_at": when.isoformat(),
            "timezone": tz,
            "confirm_publish": True,
            "linkedin_connection_id": str(connection.id),
        },
    )
    assert response.status_code == 403
    assert "w_member_social" in response.json()["error"]["message"]


@pytest.mark.asyncio
async def test_invalid_blank_and_naive_datetime(db_client, db_session, token_encryptor) -> None:
    _user, raw, connection = await seed_user_session_and_connection(
        db_session, encryptor=token_encryptor
    )
    headers = _auth_headers(raw, idempotency="idem-blank-01")
    blank = await db_client.post(
        "/api/v1/posts",
        headers=headers,
        json={
            "content": "   ",
            "scheduled_at": (datetime.now(UTC) + timedelta(hours=2)).isoformat(),
            "timezone": "UTC",
            "confirm_publish": True,
            "linkedin_connection_id": str(connection.id),
        },
    )
    assert blank.status_code == 422

    naive = await db_client.post(
        "/api/v1/posts",
        headers=_auth_headers(raw, idempotency="idem-naive-01"),
        json={
            "content": "Naive",
            "scheduled_at": "2026-12-01T10:00:00",
            "timezone": "UTC",
            "confirm_publish": True,
            "linkedin_connection_id": str(connection.id),
        },
    )
    assert naive.status_code == 422


@pytest.mark.asyncio
async def test_past_schedule_rejected(db_client, db_session, token_encryptor) -> None:
    _user, raw, connection = await seed_user_session_and_connection(
        db_session, encryptor=token_encryptor
    )
    past = datetime.now(UTC) - timedelta(minutes=5)
    response = await db_client.post(
        "/api/v1/posts",
        headers=_auth_headers(raw, idempotency="idem-past-01"),
        json={
            "content": "Too late",
            "scheduled_at": past.isoformat(),
            "timezone": "UTC",
            "confirm_publish": True,
            "linkedin_connection_id": str(connection.id),
        },
    )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_timezone_offset_mismatch(db_client, db_session, token_encryptor) -> None:
    _user, raw, connection = await seed_user_session_and_connection(
        db_session, encryptor=token_encryptor
    )
    # Instant claims +05:30 but timezone is America/New_York.
    when = datetime.now(ZoneInfo("Asia/Kolkata")) + timedelta(hours=5)
    response = await db_client.post(
        "/api/v1/posts",
        headers=_auth_headers(raw, idempotency="idem-tz-01"),
        json={
            "content": "Mismatch",
            "scheduled_at": when.isoformat(),
            "timezone": "America/New_York",
            "confirm_publish": True,
            "linkedin_connection_id": str(connection.id),
        },
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "timezone_inconsistent"


@pytest.mark.asyncio
async def test_idempotency_same_and_different_payload(
    db_client, db_session, token_encryptor
) -> None:
    _user, raw, connection = await seed_user_session_and_connection(
        db_session, encryptor=token_encryptor
    )
    when, tz = _aware(hours=4)
    payload = {
        "content": "Same payload",
        "scheduled_at": when.isoformat(),
        "timezone": tz,
        "confirm_publish": True,
        "linkedin_connection_id": str(connection.id),
    }
    first = await db_client.post(
        "/api/v1/posts",
        headers=_auth_headers(raw, idempotency="idem-dup-01"),
        json=payload,
    )
    second = await db_client.post(
        "/api/v1/posts",
        headers=_auth_headers(raw, idempotency="idem-dup-01"),
        json=payload,
    )
    assert first.status_code == 201
    assert second.status_code == 201
    assert first.json()["id"] == second.json()["id"]

    conflict = await db_client.post(
        "/api/v1/posts",
        headers=_auth_headers(raw, idempotency="idem-dup-01"),
        json={**payload, "content": "Different payload"},
    )
    assert conflict.status_code == 409
    assert conflict.json()["error"]["code"] == "idempotency_conflict"


@pytest.mark.asyncio
async def test_user_isolation(db_client, db_session, token_encryptor) -> None:
    _a, raw_a, conn_a = await seed_user_session_and_connection(
        db_session, encryptor=token_encryptor, subject="iso-a"
    )
    _b, raw_b, _conn_b = await seed_user_session_and_connection(
        db_session, encryptor=token_encryptor, subject="iso-b"
    )
    when, tz = _aware()
    created = await db_client.post(
        "/api/v1/posts",
        headers=_auth_headers(raw_a, idempotency="idem-iso-01"),
        json={
            "content": "Private",
            "scheduled_at": when.isoformat(),
            "timezone": tz,
            "confirm_publish": True,
            "linkedin_connection_id": str(conn_a.id),
        },
    )
    post_id = created.json()["id"]
    assert (
        await db_client.get(f"/api/v1/posts/{post_id}", headers=session_cookie_header(raw_b))
    ).status_code == 404
    listed = await db_client.get("/api/v1/posts", headers=session_cookie_header(raw_b))
    assert listed.status_code == 200
    assert listed.json()["items"] == []


@pytest.mark.asyncio
async def test_list_filter_and_pagination(db_client, db_session, token_encryptor) -> None:
    _user, raw, connection = await seed_user_session_and_connection(
        db_session, encryptor=token_encryptor
    )
    for i in range(3):
        when = datetime.now(UTC) + timedelta(days=2 + i)
        resp = await db_client.post(
            "/api/v1/posts",
            headers=_auth_headers(raw, idempotency=f"idem-page-{i:02d}"),
            json={
                "content": f"Post {i}",
                "scheduled_at": when.isoformat(),
                "timezone": "UTC",
                "confirm_publish": True,
                "linkedin_connection_id": str(connection.id),
            },
        )
        assert resp.status_code == 201, resp.text

    page1 = await db_client.get(
        "/api/v1/posts",
        params={"limit": 2},
        headers=session_cookie_header(raw),
    )
    assert page1.status_code == 200
    body1 = page1.json()
    assert len(body1["items"]) == 2
    assert body1["next_cursor"]

    page2 = await db_client.get(
        "/api/v1/posts",
        params={"limit": 2, "cursor": body1["next_cursor"]},
        headers=session_cookie_header(raw),
    )
    assert page2.status_code == 200, page2.text
    assert len(page2.json()["items"]) == 1


@pytest.mark.asyncio
async def test_edit_reschedule_version_and_cancel(
    db_client, db_session, token_encryptor
) -> None:
    _user, raw, connection = await seed_user_session_and_connection(
        db_session, encryptor=token_encryptor
    )
    when, tz = _aware(hours=5)
    created = await db_client.post(
        "/api/v1/posts",
        headers=_auth_headers(raw, idempotency="idem-edit-01"),
        json={
            "content": "Original",
            "scheduled_at": when.isoformat(),
            "timezone": tz,
            "confirm_publish": True,
            "linkedin_connection_id": str(connection.id),
        },
    )
    post = created.json()
    new_when = datetime.now(UTC) + timedelta(hours=8)
    stale = await db_client.patch(
        f"/api/v1/posts/{post['id']}",
        headers=_auth_headers(raw),
        json={"expected_version": 99, "content": "Stale", "confirm_publish": True},
    )
    assert stale.status_code == 409

    updated = await db_client.patch(
        f"/api/v1/posts/{post['id']}",
        headers=_auth_headers(raw),
        json={
            "expected_version": 1,
            "content": "Updated copy",
            "scheduled_at": new_when.isoformat(),
            "timezone": "UTC",
            "confirm_publish": True,
        },
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["content"] == "Updated copy"
    assert updated.json()["version"] == 2

    cancelled = await db_client.post(
        f"/api/v1/posts/{post['id']}/cancel",
        headers=_auth_headers(raw),
        json={"expected_version": 2},
    )
    assert cancelled.status_code == 200
    assert cancelled.json()["status"] == "cancelled"

    again = await db_client.post(
        f"/api/v1/posts/{post['id']}/cancel",
        headers=_auth_headers(raw),
        json={"expected_version": 3},
    )
    assert again.status_code == 200
    assert again.json()["status"] == "cancelled"

    edit_cancelled = await db_client.patch(
        f"/api/v1/posts/{post['id']}",
        headers=_auth_headers(raw),
        json={"expected_version": 3, "content": "Nope", "confirm_publish": True},
    )
    assert edit_cancelled.status_code == 409


@pytest.mark.asyncio
async def test_cannot_edit_processing_or_published(
    db_client, db_session, token_encryptor
) -> None:
    _user, raw, connection = await seed_user_session_and_connection(
        db_session, encryptor=token_encryptor
    )
    when, tz = _aware()
    created = await db_client.post(
        "/api/v1/posts",
        headers=_auth_headers(raw, idempotency="idem-proc-01"),
        json={
            "content": "Locked later",
            "scheduled_at": when.isoformat(),
            "timezone": tz,
            "confirm_publish": True,
            "linkedin_connection_id": str(connection.id),
        },
    )
    post_id = UUID(created.json()["id"])
    row = (
        await db_session.execute(select(ScheduledPost).where(ScheduledPost.id == post_id))
    ).scalar_one()
    row.status = PostStatus.PROCESSING.value
    await db_session.commit()

    response = await db_client.patch(
        f"/api/v1/posts/{post_id}",
        headers=_auth_headers(raw),
        json={"expected_version": 1, "content": "No", "confirm_publish": True},
    )
    assert response.status_code == 409

    row.status = PostStatus.PUBLISHED.value
    await db_session.commit()
    cancel = await db_client.post(
        f"/api/v1/posts/{post_id}/cancel",
        headers=_auth_headers(raw),
        json={"expected_version": 1},
    )
    assert cancel.status_code == 409


@pytest.mark.asyncio
async def test_connection_expiry_warning(db_client, db_session, token_encryptor) -> None:
    soon = datetime.now(UTC) + timedelta(hours=1)
    _user, raw, connection = await seed_user_session_and_connection(
        db_session,
        encryptor=token_encryptor,
        token_expires_at=soon,
    )
    when = datetime.now(UTC) + timedelta(days=2)
    response = await db_client.post(
        "/api/v1/posts",
        headers=_auth_headers(raw, idempotency="idem-exp-01"),
        json={
            "content": "Token expires first",
            "scheduled_at": when.isoformat(),
            "timezone": "UTC",
            "confirm_publish": True,
            "linkedin_connection_id": str(connection.id),
        },
    )
    assert response.status_code == 201
    body = response.json()
    assert body["connection_expires_before_schedule"] is True
    assert body["connection_expiry_warning"]


@pytest.mark.asyncio
async def test_missing_idempotency_header(db_client, db_session, token_encryptor) -> None:
    _user, raw, connection = await seed_user_session_and_connection(
        db_session, encryptor=token_encryptor
    )
    when, tz = _aware()
    response = await db_client.post(
        "/api/v1/posts",
        headers=_auth_headers(raw),
        json={
            "content": "No key",
            "scheduled_at": when.isoformat(),
            "timezone": tz,
            "confirm_publish": True,
            "linkedin_connection_id": str(connection.id),
        },
    )
    assert response.status_code == 422
