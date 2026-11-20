"""Read-only LinkedIn publishing readiness diagnostics (no secrets)."""

from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class ReadinessCheck(BaseModel):
    model_config = ConfigDict(extra="forbid")

    key: str
    ok: bool
    detail: str


class PublishingReadinessResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # High-level buckets — never claim "verified" without a real persisted LinkedIn URN.
    configured: bool
    ready_for_test: bool
    publishing_verified: bool

    publish_provider: str
    enable_real_publishing: bool
    live_publish_require_canary: bool
    canary_post_ids: list[UUID] = Field(default_factory=list)
    linkedin_api_version: str
    person_urn: str | None = None

    selected_post_id: UUID | None = None
    selected_post_canary_approved: bool | None = None
    selected_post_status: str | None = None

    pending_scheduled_posts: int = 0
    pending_scheduled_non_canary: int = 0

    checks: list[ReadinessCheck] = Field(default_factory=list)
