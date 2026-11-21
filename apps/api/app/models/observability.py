"""Persisted AI observability: LLM usage, node traces, pricing versions."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
    Uuid,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import JSON

from app.db.base import Base

_JSON = JSON().with_variant(JSONB(), "postgresql")


class ModelPricingVersion(Base):
    """Immutable pricing snapshot used for historical cost calculations."""

    __tablename__ = "model_pricing_versions"
    __table_args__ = (
        UniqueConstraint(
            "pricing_version",
            "model",
            name="uq_model_pricing_versions_version_model",
        ),
        Index("ix_model_pricing_versions_model", "model"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    pricing_version: Mapped[str] = mapped_column(String(64), nullable=False)
    model: Mapped[str] = mapped_column(String(128), nullable=False)
    provider: Mapped[str] = mapped_column(String(32), nullable=False, default="openai")
    currency: Mapped[str] = mapped_column(String(8), nullable=False, default="USD")
    input_per_million: Mapped[Decimal] = mapped_column(Numeric(18, 8), nullable=False)
    cached_input_per_million: Mapped[Decimal | None] = mapped_column(Numeric(18, 8), nullable=True)
    output_per_million: Mapped[Decimal] = mapped_column(Numeric(18, 8), nullable=False)
    effective_date: Mapped[date] = mapped_column(Date, nullable=False)
    source: Mapped[str] = mapped_column(String(512), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class LLMUsageEvent(Base):
    """One LLM API invocation (append-only)."""

    __tablename__ = "llm_usage_events"
    __table_args__ = (
        UniqueConstraint("idempotency_key", name="uq_llm_usage_events_idempotency"),
        Index("ix_llm_usage_events_user_created", "user_id", "created_at"),
        Index("ix_llm_usage_events_thread_created", "thread_id", "created_at"),
        Index("ix_llm_usage_events_trace", "trace_id"),
        Index("ix_llm_usage_events_model_created", "model", "created_at"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False)
    trace_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    turn_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)
    user_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    thread_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("agent_threads.id", ondelete="SET NULL"), nullable=True
    )
    node_name: Mapped[str] = mapped_column(String(64), nullable=False)
    schema_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    provider: Mapped[str] = mapped_column(String(32), nullable=False)
    model: Mapped[str] = mapped_column(String(128), nullable=False)
    success: Mapped[bool] = mapped_column(Boolean, nullable=False)
    error_category: Mapped[str | None] = mapped_column(String(64), nullable=True)
    # Null means unknown — never store fabricated zeros as known usage.
    usage_known: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    input_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    output_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    cached_input_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    total_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    provider_request_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    latency_ms: Mapped[int] = mapped_column(Integer, nullable=False)
    # Estimated cost snapshot; null when unavailable. pricing_version freezes the rate.
    estimated_cost: Mapped[Decimal | None] = mapped_column(Numeric(18, 8), nullable=True)
    cost_currency: Mapped[str | None] = mapped_column(String(8), nullable=True)
    pricing_version: Mapped[str | None] = mapped_column(String(64), nullable=True)
    cost_available: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    requested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class AgentNodeTrace(Base):
    """LangGraph node execution span (no prompt bodies / credentials)."""

    __tablename__ = "agent_node_traces"
    __table_args__ = (
        UniqueConstraint("idempotency_key", name="uq_agent_node_traces_idempotency"),
        Index("ix_agent_node_traces_user_started", "user_id", "started_at"),
        Index("ix_agent_node_traces_thread_started", "thread_id", "started_at"),
        Index("ix_agent_node_traces_trace", "trace_id"),
        Index("ix_agent_node_traces_node", "node_name", "started_at"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False)
    trace_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    turn_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)
    user_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    thread_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("agent_threads.id", ondelete="SET NULL"), nullable=True
    )
    node_name: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    provider: Mapped[str | None] = mapped_column(String(32), nullable=True)
    model: Mapped[str | None] = mapped_column(String(128), nullable=True)
    usage_event_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("llm_usage_events.id", ondelete="SET NULL"), nullable=True
    )
    duration_ms: Mapped[int] = mapped_column(Integer, nullable=False)
    error_category: Mapped[str | None] = mapped_column(String(64), nullable=True)
    review_passed: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    revision_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # Sanitized metadata only (schema name, response_state) — never prompts or tokens secrets.
    meta: Mapped[dict[str, Any]] = mapped_column(_JSON, nullable=False, default=dict)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    ended_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
