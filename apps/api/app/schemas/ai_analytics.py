"""Admin AI analytics API schemas."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class AiAnalyticsSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    from_time: datetime
    to_time: datetime
    total_llm_requests: int
    successful_llm_requests: int
    failed_llm_requests: int
    total_input_tokens: int | None = Field(
        description="Sum of known input tokens; null if no known usage in range."
    )
    total_output_tokens: int | None
    total_cached_input_tokens: int | None
    usage_known_requests: int
    usage_unknown_requests: int
    total_estimated_cost: Decimal | None
    cost_currency: str = "USD"
    cost_label: str = "estimate (not official provider billing)"
    cost_available_requests: int
    avg_latency_ms: float | None
    p95_latency_ms: float | None
    review_traces: int
    review_failures: int
    review_failure_rate: float | None
    automatic_revision_traces: int
    drafts_generated: int
    approved_ai_drafts_scheduled: int
    requests_by_model: list[dict[str, Any]]
    cost_per_user: list[dict[str, Any]]
    cost_per_conversation: list[dict[str, Any]]


class ThreadInspectionResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    thread_id: UUID
    user_id: UUID
    title: str | None
    status: str
    created_at: datetime
    updated_at: datetime
    message_count: int
    draft_version: int | None
    draft_status: str | None
    scheduled_post_id: UUID | None
    schedule_ops: list[dict[str, Any]]
    traces: list[dict[str, Any]]
    usage_events: list[dict[str, Any]]
    note: str = (
        "Message bodies, prompts, and credentials are omitted. "
        "Costs are estimates using frozen pricing_version values."
    )
