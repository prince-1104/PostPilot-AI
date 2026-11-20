"""Typed payloads returned by LinkedIn OAuth and OIDC endpoints."""

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True, slots=True)
class LinkedInTokenResponse:
    access_token: str
    expires_in: int
    id_token: str
    # None when LinkedIn omitted the field. Empty string is treated as malformed upstream.
    scope: str | None
    token_type: str = "Bearer"  # noqa: S105


@dataclass(frozen=True, slots=True)
class LinkedInTokenIntrospection:
    active: bool
    client_id: str | None
    # Raw comma-delimited scope string from LinkedIn, or None when omitted.
    scope: str | None
    status: str | None = None


@dataclass(frozen=True, slots=True)
class LinkedInUserInfo:
    sub: str
    name: str
    email: str | None
    picture: str | None


@dataclass(frozen=True, slots=True)
class ValidatedIdToken:
    subject: str
    issuer: str
    audience: str
    expires_at: datetime
