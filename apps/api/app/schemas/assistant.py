"""HTTP schemas for the Phase 5A/5B/5C AI assistant."""

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.schemas.posts import ScheduledPostResponse

AssistantState = Literal[
    "needs_information",
    "generating",
    "draft_ready",
    "unavailable",
    "error",
]

WritingStyle = Literal[
    "professional",
    "conversational",
    "concise",
    "detailed",
    "promotional",
]

DraftActionType = Literal["regenerate", "rewrite", "set_tone"]


class CreateAssistantThread(BaseModel):
    model_config = ConfigDict(extra="forbid")

    timezone: str | None = Field(default=None, max_length=64)
    title: str | None = Field(default=None, max_length=255)


class PostAssistantMessage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    content: str = Field(min_length=1, max_length=4000)
    timezone: str | None = Field(default=None, max_length=64)
    client_message_id: UUID | None = None
    tone: WritingStyle | None = None

    @field_validator("content")
    @classmethod
    def _strip(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("content must not be blank")
        return stripped


class PatchAssistantDraft(BaseModel):
    model_config = ConfigDict(extra="forbid")

    content: str = Field(min_length=1, max_length=3000)
    expected_version: int = Field(ge=1)
    expected_lock_version: int | None = Field(default=None, ge=0)

    @field_validator("content")
    @classmethod
    def _strip(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("content must not be blank")
        return stripped


class AssistantDraftAction(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action: DraftActionType
    instruction: str | None = Field(default=None, max_length=2000)
    tone: WritingStyle | None = None
    expected_version: int | None = Field(default=None, ge=1)
    client_message_id: UUID | None = None

    @field_validator("instruction")
    @classmethod
    def _strip_instruction(cls, value: str | None) -> str | None:
        if value is None:
            return None
        stripped = value.strip()
        return stripped or None


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
    scheduled_post_id: UUID | None = None
    label: str = "Draft — not scheduled"
    created_at: datetime
    updated_at: datetime


class AssistantSchedulePreviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_draft_version: int = Field(ge=1)
    content: str | None = Field(default=None, min_length=1, max_length=3000)
    linkedin_connection_id: UUID
    scheduled_at: datetime
    timezone: str = Field(min_length=1, max_length=64)
    acknowledge_warnings: bool = False

    @field_validator("content")
    @classmethod
    def _strip_content(cls, value: str | None) -> str | None:
        if value is None:
            return None
        stripped = value.strip()
        if not stripped:
            raise ValueError("content must not be blank")
        return stripped

    @field_validator("scheduled_at")
    @classmethod
    def _require_aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("scheduled_at must be timezone-aware (include an offset)")
        return value

    @field_validator("timezone")
    @classmethod
    def _strip_timezone(cls, value: str) -> str:
        return value.strip()


class AssistantScheduleConfirmRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_draft_version: int = Field(ge=1)
    content: str = Field(min_length=1, max_length=3000)
    linkedin_connection_id: UUID
    scheduled_at: datetime
    timezone: str = Field(min_length=1, max_length=64)
    confirm_schedule: bool
    acknowledge_warnings: bool = False

    @field_validator("content")
    @classmethod
    def _strip_content(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("content must not be blank")
        return stripped

    @field_validator("scheduled_at")
    @classmethod
    def _require_aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("scheduled_at must be timezone-aware (include an offset)")
        return value

    @field_validator("timezone")
    @classmethod
    def _strip_timezone(cls, value: str) -> str:
        return value.strip()

    @field_validator("confirm_schedule")
    @classmethod
    def _require_confirm(cls, value: bool) -> bool:
        if value is not True:
            raise ValueError("confirm_schedule must be true to create a scheduled post")
        return value


class AssistantSchedulePreviewResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    draft_id: UUID
    draft_version: int
    content: str
    linkedin_connection_id: UUID
    linkedin_display_name: str | None
    scheduled_at_local: str
    timezone: str
    scheduled_at_utc: datetime
    approval_warnings: list[str] = Field(default_factory=list)
    advisory_warnings: list[str] = Field(default_factory=list)
    hard_blockers: list[str] = Field(default_factory=list)
    connection_expiry_warning: str | None = None
    can_confirm: bool
    label: str = "Draft — not scheduled"


class AssistantScheduleConfirmResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    draft_id: UUID
    draft_version: int
    scheduled_post_id: UUID
    post: ScheduledPostResponse
    idempotent_replay: bool = False
    message: str = "Scheduled via existing PostService. Celery will publish when due."


class AssistantThreadSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: UUID
    status: str
    title: str | None
    created_at: datetime
    updated_at: datetime
    response_state: AssistantState | None = None
    current_stage: str | None = None


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
    current_stage: str | None = None
    writing_style: WritingStyle | None = None
    review_issues: list[str] = Field(default_factory=list)
    review_suggestions: list[str] = Field(default_factory=list)
    validation_errors: list[str] = Field(default_factory=list)
    lock_version: int = 0
    assistant_ready: bool


class AssistantTurnResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    thread_id: UUID
    state: AssistantState
    current_stage: str | None = None
    assistant_message: AssistantMessageResponse | None
    clarification_questions: list[str] = Field(default_factory=list)
    draft: AssistantDraftResponse | None
    proposed_scheduled_at: datetime | None = None
    timezone: str | None = None
    writing_style: WritingStyle | None = None
    review_issues: list[str] = Field(default_factory=list)
    review_suggestions: list[str] = Field(default_factory=list)
    validation_errors: list[str] = Field(default_factory=list)
    lock_version: int = 0
    idempotent_replay: bool = False


class AssistantStatusResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ai_enabled: bool
    ai_ready: bool
    provider: str
    model: str | None
    message: str
