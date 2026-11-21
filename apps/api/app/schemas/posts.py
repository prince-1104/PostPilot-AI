"""Scheduled post request and response models."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator


class CreateScheduledPost(BaseModel):
    model_config = ConfigDict(extra="forbid")

    content: str = Field(min_length=1)
    scheduled_at: datetime
    timezone: str = Field(min_length=1, max_length=64)
    linkedin_connection_id: UUID
    # Explicit Schedule & Publish confirmation from the authenticated UI.
    confirm_publish: bool

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

    @field_validator("confirm_publish")
    @classmethod
    def _require_confirm(cls, value: bool) -> bool:
        if value is not True:
            raise ValueError("confirm_publish must be true to schedule for LinkedIn publishing")
        return value


class UpdateScheduledPost(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_version: int = Field(ge=1)
    content: str | None = Field(default=None, min_length=1)
    scheduled_at: datetime | None = None
    timezone: str | None = Field(default=None, min_length=1, max_length=64)
    # Required true when content/schedule/timezone change (renews approval).
    confirm_publish: bool | None = None

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
    def _require_aware(cls, value: datetime | None) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("scheduled_at must be timezone-aware (include an offset)")
        return value

    @field_validator("timezone")
    @classmethod
    def _strip_timezone(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return value.strip()


class CancelScheduledPost(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_version: int = Field(ge=1)


class ApproveScheduledPost(BaseModel):
    """Explicitly approve an existing scheduled post for LinkedIn publication."""

    model_config = ConfigDict(extra="forbid")

    expected_version: int = Field(ge=1)
    confirm_publish: bool

    @field_validator("confirm_publish")
    @classmethod
    def _require_confirm(cls, value: bool) -> bool:
        if value is not True:
            raise ValueError("confirm_publish must be true to approve publishing")
        return value


class ScheduledPostResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: UUID
    linkedin_connection_id: UUID
    content: str
    scheduled_at: datetime
    timezone: str
    status: str
    version: int
    created_at: datetime
    updated_at: datetime
    published_at: datetime | None = None
    linkedin_post_urn: str | None = None
    attempt_count: int = 0
    next_attempt_at: datetime | None = None
    last_error_code: str | None = None
    last_error_at: datetime | None = None
    # True when linkedin_post_urn is a Phase 4A simulation URN.
    publication_simulated: bool = False
    linkedin_permalink: str | None = None
    # Present when the LinkedIn access token expires before scheduled_at.
    connection_expires_before_schedule: bool = False
    connection_expiry_warning: str | None = None
    reconnect_required: bool = False
    publish_approved: bool = False
    publish_approved_at: datetime | None = None
    publish_approved_by: UUID | None = None
    approval_revoked_at: datetime | None = None


class ScheduledPostListResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[ScheduledPostResponse]
    next_cursor: str | None = None


class PublishAttemptResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: UUID
    attempt_number: int
    execution_state: str
    started_at: datetime
    request_started_at: datetime | None = None
    finished_at: datetime | None = None
    provider_http_status: int | None = None
    error_category: str | None = None
    sanitized_error_code: str | None = None
    next_retry_at: datetime | None = None
    provider_post_urn: str | None = None
    publication_simulated: bool = False


class PublishAttemptListResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[PublishAttemptResponse]
