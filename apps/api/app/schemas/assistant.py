"""HTTP schemas for the Phase 5A AI assistant."""

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

AssistantState = Literal[
    "needs_information",
    "generating",
    "draft_ready",
    "unavailable",
    "error",
]


class CreateAssistantThread(BaseModel):
    model_config = ConfigDict(extra="forbid")

    timezone: str | None = Field(default=None, max_length=64)
    title: str | None = Field(default=None, max_length=255)


class PostAssistantMessage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    content: str = Field(min_length=1, max_length=4000)
    timezone: str | None = Field(default=None, max_length=64)

    @field_validator("content")
    @classmethod
    def _strip(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("content must not be blank")
        return stripped


class AssistantMessageResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: UUID
    role: str
    content: str
    created_at: datetime


class AssistantDraftResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: UUID
    content: str
    category: str | None
    confirmed_facts: dict[str, Any]
    suggested_details: dict[str, Any]
    assumptions: dict[str, Any] | list[Any]
    proposed_scheduled_at: datetime | None
    timezone: str | None
    status: str
    version: int
    label: str = "Draft — not scheduled"
    created_at: datetime
    updated_at: datetime


class AssistantThreadSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: UUID
    status: str
    title: str | None
    created_at: datetime
    updated_at: datetime
    response_state: AssistantState | None = None


class AssistantThreadDetail(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: UUID
    status: str
    title: str | None
    created_at: datetime
    updated_at: datetime
    messages: list[AssistantMessageResponse]
    draft: AssistantDraftResponse | None
    clarification_questions: list[str] = Field(default_factory=list)
    response_state: AssistantState
    assistant_ready: bool


class AssistantTurnResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    thread_id: UUID
    state: AssistantState
    assistant_message: AssistantMessageResponse | None
    clarification_questions: list[str] = Field(default_factory=list)
    draft: AssistantDraftResponse | None
    proposed_scheduled_at: datetime | None = None
    timezone: str | None = None


class AssistantStatusResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ai_enabled: bool
    ai_ready: bool
    provider: str
    model: str | None
    message: str
