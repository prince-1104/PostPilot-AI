"""Structured LLM I/O and graph-facing Pydantic models for Phase 5A/5B.

OpenAI strict structured outputs require:
- every property listed in ``required``
- no free-form ``dict`` / ``additionalProperties`` objects

Fact maps therefore use ``[{key, value}, ...]`` for LLM I/O and convert to
``dict[str, str]`` at the graph boundary.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

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

WritingStyle = Literal[
    "professional",
    "conversational",
    "concise",
    "detailed",
    "promotional",
]

AssistantStage = Literal[
    "intent",
    "requirements",
    "awaiting_user",
    "writing",
    "reviewing",
    "revising",
    "validating",
    "draft_ready",
    "error",
]


class FactEntry(BaseModel):
    """OpenAI-safe key/value fact (replaces free-form dicts in structured output)."""

    model_config = ConfigDict(extra="forbid")

    key: str
    value: str


def facts_to_dict(entries: list[FactEntry] | dict[str, str] | None) -> dict[str, str]:
    if not entries:
        return {}
    if isinstance(entries, dict):
        return {str(k): str(v) for k, v in entries.items() if str(k).strip() and str(v).strip()}
    out: dict[str, str] = {}
    for item in entries:
        key = item.key.strip()
        value = item.value.strip()
        if key and value:
            out[key] = value
    return out


def dict_to_facts(data: dict[str, str] | None) -> list[FactEntry]:
    if not data:
        return []
    return [FactEntry(key=str(k), value=str(v)) for k, v in data.items() if str(k) and str(v)]


def _coerce_fact_entries(value: Any) -> list[dict[str, str]] | Any:
    if value is None:
        return []
    if isinstance(value, dict):
        return [{"key": str(k), "value": str(v)} for k, v in value.items()]
    return value


class IntentResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    intent_type: IntentType
    post_category: PostCategory
    extracted_facts: list[FactEntry]
    requested_schedule_text: str | None
    missing_hints: list[str]
    injection_attempt: bool
    writing_style: WritingStyle | None
    refine_instruction: str | None
    notes: str | None

    @field_validator("extracted_facts", mode="before")
    @classmethod
    def _facts(cls, value: Any) -> Any:
        return _coerce_fact_entries(value)

    @model_validator(mode="before")
    @classmethod
    def _defaults_for_fake(cls, value: Any) -> Any:
        # Keep FakeLLM compact overrides working while satisfying OpenAI required fields.
        if not isinstance(value, dict):
            return value
        data = dict(value)
        data.setdefault("post_category", "general")
        data.setdefault("extracted_facts", [])
        data.setdefault("requested_schedule_text", None)
        data.setdefault("missing_hints", [])
        data.setdefault("injection_attempt", False)
        data.setdefault("writing_style", None)
        data.setdefault("refine_instruction", None)
        data.setdefault("notes", None)
        return data

    @property
    def extracted_facts_map(self) -> dict[str, str]:
        return facts_to_dict(self.extracted_facts)


class RequirementsResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    confirmed_facts: list[FactEntry]
    optional_preferences: list[FactEntry]
    missing_required_fields: list[str]
    clarification_questions: list[str]
    ready_to_draft: bool

    @field_validator("confirmed_facts", "optional_preferences", mode="before")
    @classmethod
    def _facts(cls, value: Any) -> Any:
        return _coerce_fact_entries(value)

    @model_validator(mode="before")
    @classmethod
    def _defaults_for_fake(cls, value: Any) -> Any:
        if not isinstance(value, dict):
            return value
        data = dict(value)
        data.setdefault("confirmed_facts", [])
        data.setdefault("optional_preferences", [])
        data.setdefault("missing_required_fields", [])
        data.setdefault("clarification_questions", [])
        data.setdefault("ready_to_draft", False)
        return data

    @property
    def confirmed_facts_map(self) -> dict[str, str]:
        return facts_to_dict(self.confirmed_facts)

    @property
    def optional_preferences_map(self) -> dict[str, str]:
        return facts_to_dict(self.optional_preferences)


class WritingResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    content: str = Field(min_length=1, max_length=3000)
    suggested_hashtags: list[str]
    confirmed_facts_used: list[FactEntry]
    assumptions: list[str]
    missing_information: list[str]
    quality_warnings: list[str]
    suggested_skills: list[str]
    suggested_responsibilities: list[str]

    @field_validator("confirmed_facts_used", mode="before")
    @classmethod
    def _facts(cls, value: Any) -> Any:
        return _coerce_fact_entries(value)

    @model_validator(mode="before")
    @classmethod
    def _defaults_for_fake(cls, value: Any) -> Any:
        if not isinstance(value, dict):
            return value
        data = dict(value)
        data.setdefault("suggested_hashtags", [])
        data.setdefault("confirmed_facts_used", [])
        data.setdefault("assumptions", [])
        data.setdefault("missing_information", [])
        data.setdefault("quality_warnings", [])
        data.setdefault("suggested_skills", [])
        data.setdefault("suggested_responsibilities", [])
        return data

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
        return cleaned[:8]

    @field_validator("suggested_skills", "suggested_responsibilities")
    @classmethod
    def _trim_suggestions(cls, value: list[str]) -> list[str]:
        return [item.strip()[:200] for item in value if item and item.strip()][:12]

    @property
    def confirmed_facts_used_map(self) -> dict[str, str]:
        return facts_to_dict(self.confirmed_facts_used)


class ReviewResult(BaseModel):
    """Advisory LLM review — never treated as ground-truth verification."""

    model_config = ConfigDict(extra="forbid")

    passed: bool
    issues: list[str]
    suggestions: list[str]
    unsupported_claims: list[str]
    missing_required_facts: list[str]
    proposed_revision: str | None

    @model_validator(mode="before")
    @classmethod
    def _defaults_for_fake(cls, value: Any) -> Any:
        if not isinstance(value, dict):
            return value
        data = dict(value)
        data.setdefault("issues", [])
        data.setdefault("suggestions", [])
        data.setdefault("unsupported_claims", [])
        data.setdefault("missing_required_facts", [])
        data.setdefault("proposed_revision", None)
        return data


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
    suggested_skills: list[str] = Field(default_factory=list)
    suggested_responsibilities: list[str] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)
    writing_style: WritingStyle = "professional"
    refine_instruction: str | None = None
    review_passed: bool | None = None
    review_issues: list[str] = Field(default_factory=list)
    review_suggestions: list[str] = Field(default_factory=list)
    unsupported_claims: list[str] = Field(default_factory=list)
    auto_revision_count: int = 0
    llm_calls_this_turn: int = 0
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
