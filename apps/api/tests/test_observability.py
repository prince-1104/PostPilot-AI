"""Phase 5D observability: usage capture, pricing, admin gate, guardrails."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid4

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from app.assistant.llm.fake import FakeLLMProvider
from app.assistant.llm.openai_provider import _usage_from_completion
from app.main import create_app
from app.observability.pricing import estimate_cost
from app.observability.recorder import ObservabilityRecorder
from app.observability.usage import LLMUsage
from tests.conftest import seed_user_session_and_connection, session_cookie_header


def _auth(raw: str) -> dict[str, str]:
    return {**session_cookie_header(raw), "Origin": "http://localhost:3000"}


def test_unknown_usage_not_reported_as_zero() -> None:
    usage = _usage_from_completion(
        object(), model="gpt-4o-mini", latency_ms=12.0, success=True
    )
    assert usage.usage_known is False
    assert usage.input_tokens is None
    assert usage.output_tokens is None
    cost = estimate_cost(
        model="gpt-4o-mini",
        input_tokens=usage.input_tokens,
        output_tokens=usage.output_tokens,
        cached_input_tokens=usage.cached_input_tokens,
    )
    assert cost.available is False
    assert cost.amount is None


def test_cost_matches_configured_pricing_and_cached_not_double_counted() -> None:
    cost = estimate_cost(
        model="gpt-4o-mini",
        input_tokens=1_000_000,
        output_tokens=1_000_000,
        cached_input_tokens=500_000,
    )
    assert cost.available is True
    # (500k non-cached * 0.15 + 500k cached * 0.075 + 1M out * 0.60) / 1M
    expected = Decimal("0.15") * Decimal("0.5") + Decimal("0.075") * Decimal("0.5") + Decimal(
        "0.60"
    )
    assert cost.amount == expected.quantize(Decimal("0.00000001"))
    assert cost.pricing_version is not None


def test_unknown_model_cost_unavailable() -> None:
    cost = estimate_cost(
        model="totally-unknown-model",
        input_tokens=10,
        output_tokens=10,
        cached_input_tokens=None,
    )
    assert cost.available is False


@pytest.mark.asyncio
async def test_fake_provider_marks_usage_unknown() -> None:
    from app.assistant.schemas import IntentResult

    result = await FakeLLMProvider().complete_structured(
        system="sys", user="hiring AI Engineer", schema=IntentResult
    )
    assert result.usage.usage_known is False
    assert result.usage.input_tokens is None


@pytest.fixture
def ai_settings(settings_factory):
    return settings_factory(
        ai_enabled=True,
        ai_provider="fake",
        ai_model="fake-model",
        publish_provider="fake",
        enable_real_publishing=False,
        admin_emails=["admin@example.com"],
        admin_user_ids=[],
    )


@pytest.fixture
async def ai_client(ai_settings, sqlite_engine: AsyncEngine):
    app: FastAPI = create_app(ai_settings)
    async with app.router.lifespan_context(app):
        app.state.session_factory = async_sessionmaker(sqlite_engine, expire_on_commit=False)
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            yield client


@pytest.mark.asyncio
async def test_ordinary_user_cannot_read_admin_analytics(
    ai_client, db_session, token_encryptor
) -> None:
    _user, raw, _conn = await seed_user_session_and_connection(
        db_session, encryptor=token_encryptor, subject=f"obs-user-{uuid4()}"
    )
    resp = await ai_client.get("/api/v1/admin/ai/analytics", headers=_auth(raw))
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_admin_can_read_analytics(ai_client, db_session, token_encryptor) -> None:
    from sqlalchemy import select

    from app.models import User

    _user, raw, _conn = await seed_user_session_and_connection(
        db_session, encryptor=token_encryptor, subject=f"obs-admin-{uuid4()}"
    )
    row = (
        await db_session.execute(select(User).where(User.id == _user.id))
    ).scalar_one()
    row.email = "admin@example.com"
    await db_session.commit()
    resp = await ai_client.get("/api/v1/admin/ai/analytics?preset=7d", headers=_auth(raw))
    assert resp.status_code == 200
    body = resp.json()
    assert body["total_llm_requests"] == 0
    assert "estimate" in body["cost_label"]


@pytest.mark.asyncio
async def test_usage_event_idempotent_and_no_secrets(
    ai_settings, sqlite_engine: AsyncEngine
) -> None:
    factory = async_sessionmaker(sqlite_engine, expire_on_commit=False)
    recorder = ObservabilityRecorder(factory)
    usage = LLMUsage(
        provider="openai",
        model="gpt-4o-mini",
        success=True,
        latency_ms=10,
        input_tokens=100,
        output_tokens=50,
        cached_input_tokens=10,
        total_tokens=150,
        usage_known=True,
        node_name="intent",
        schema_name="IntentResult",
    )
    user_id = uuid4()
    # Need a user FK — create minimal user row
    from app.models import User

    async with factory() as session:
        session.add(
            User(
                id=user_id,
                linkedin_subject=f"obs-{uuid4()}",
                display_name="Obs",
                email="obs@example.com",
                created_at=datetime.now(UTC),
                updated_at=datetime.now(UTC),
            )
        )
        await session.commit()

    key = f"idem-{uuid4()}"
    first = await recorder.record_llm_usage(
        usage=usage,
        user_id=user_id,
        thread_id=None,
        trace_id=uuid4(),
        turn_id=uuid4(),
        idempotency_key=key,
    )
    second = await recorder.record_llm_usage(
        usage=usage,
        user_id=user_id,
        thread_id=None,
        trace_id=uuid4(),
        turn_id=uuid4(),
        idempotency_key=key,
    )
    assert first is not None
    assert second is None

    await recorder.record_node_trace(
        user_id=user_id,
        thread_id=None,
        trace_id=uuid4(),
        turn_id=uuid4(),
        node_name="intent",
        status="ok",
        started_at=datetime.now(UTC),
        ended_at=datetime.now(UTC),
        duration_ms=5,
        idempotency_key=f"trace-{uuid4()}",
        meta={"prompt": "SECRET SHOULD DROP", "schema_name": "IntentResult"},
    )
    from sqlalchemy import select

    from app.models.observability import AgentNodeTrace

    async with factory() as session:
        row = (await session.execute(select(AgentNodeTrace))).scalar_one()
        assert "prompt" not in row.meta
        assert row.meta.get("schema_name") == "IntentResult"


@pytest.mark.asyncio
async def test_turn_records_usage_without_corrupting_draft(
    ai_client, db_session, token_encryptor
) -> None:
    _user, raw, _conn = await seed_user_session_and_connection(
        db_session, encryptor=token_encryptor, subject=f"obs-draft-{uuid4()}"
    )
    created = await ai_client.post(
        "/api/v1/assistant/threads",
        headers=_auth(raw),
        json={"timezone": "UTC"},
    )
    assert created.status_code == 201
    thread_id = created.json()["id"]
    turn = await ai_client.post(
        f"/api/v1/assistant/threads/{thread_id}/messages",
        headers=_auth(raw),
        json={
            "content": (
                "Hiring Backend Engineer. Company is Acme. Remote. 4 years experience."
            ),
            "timezone": "UTC",
        },
    )
    assert turn.status_code == 200
    assert turn.json()["state"] == "draft_ready"
    assert turn.json()["draft"] is not None
