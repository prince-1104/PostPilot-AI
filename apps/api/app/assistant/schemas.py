"""Structured LLM I/O and graph-facing Pydantic models for Phase 5A."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

PostCategory = Literal[
    "job_announcement",
    "product_launch",
    "professional_update",
    "educational",
    "event_announcement",
    "general",
]

IntentType = Literal[
    "create_scheduled_post",
    "create_post_draft",
    "refine_draft",
    "clarify",
    "unsupported",
]

AssistantStage = Literal[
    "intent",
    "requirements",
    "awaiting_user",
    "writing",
    "validating",
    "draft_ready",
    "error",
]


class IntentResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    intent_type: IntentType
    post_category: PostCategory = "general"
    extracted_facts: dict[str, str] = Field(default_factory=dict)
    requested_schedule_text: str | None = None
    missing_hints: list[str] = Field(default_factory=list)
    injection_attempt: bool = False
    notes: str | None = None


class RequirementsResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    confirmed_facts: dict[str, str] = Field(default_factory=dict)
    optional_preferences: dict[str, str] = Field(default_factory=dict)
    missing_required_fields: list[str] = Field(default_factory=list)
    clarification_questions: list[str] = Field(default_factory=list)
    ready_to_draft: bool = False


class WritingResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    content: str = Field(min_length=1, max_length=3000)
    suggested_hashtags: list[str] = Field(default_factory=list)
    confirmed_facts_used: dict[str, str] = Field(default_factory=dict)
    assumptions: list[str] = Field(default_factory=list)
    missing_information: list[str] = Field(default_factory=list)
    quality_warnings: list[str] = Field(default_factory=list)

    @field_validator("suggested_hashtags")
    @classmethod
    def _normalize_tags(cls, value: list[str]) -> list[str]:
        cleaned: list[str] = []
        for tag in value:
            t = tag.strip()
            if not t:
                continue
            if not t.startswith("#"):
                t = f"#{t}"
            cleaned.append(t[:64])
        return cleaned[:12]


class GraphSnapshot(BaseModel):
    """Serializable LangGraph working state persisted on agent_threads.graph_state."""

    model_config = ConfigDict(extra="forbid")

    thread_id: str
    user_id: str
    intent_type: IntentType | None = None
    post_category: PostCategory | None = None
    confirmed_facts: dict[str, str] = Field(default_factory=dict)
    optional_preferences: dict[str, str] = Field(default_factory=dict)
    missing_required_fields: list[str] = Field(default_factory=list)
    clarification_questions: list[str] = Field(default_factory=list)
    requested_schedule_text: str | None = None
    proposed_scheduled_at: datetime | None = None
    timezone: str | None = None
    draft_content: str | None = None
    suggested_hashtags: list[str] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)
    current_stage: AssistantStage = "intent"
    validation_errors: list[str] = Field(default_factory=list)
    last_user_message: str | None = None
    assistant_reply: str | None = None
    response_state: Literal[
        "needs_information", "generating", "draft_ready", "unavailable", "error"
    ] = "generating"
    injection_attempt: bool = False

    @field_validator("assumptions", mode="before")
    @classmethod
    def _coerce_assumptions(cls, value: Any) -> list[str]:
        if value is None:
            return []
        if isinstance(value, dict):
            return [f"{k}: {v}" for k, v in value.items()]
        if isinstance(value, list):
            return [str(item) for item in value]
        return [str(value)]
