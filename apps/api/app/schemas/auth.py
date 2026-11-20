"""Auth and connection API response models. Tokens never appear here."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class UserProfileResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: UUID
    display_name: str
    email: str | None
    avatar_url: str | None
    linkedin_subject: str


class LinkedInConnectionResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    connected: bool
    connection_status: str
    # Present when a LinkedIn connection row exists (including reauth / disconnected).
    id: UUID | None = None
    display_name: str | None = None
    avatar_url: str | None = None
    granted_scopes: list[str] = Field(default_factory=list)
    token_expires_at: datetime | None = None
    reauthorization_required: bool = False
    # Local disconnect does not revoke the grant at LinkedIn.
    disconnect_is_local_only: bool = True
