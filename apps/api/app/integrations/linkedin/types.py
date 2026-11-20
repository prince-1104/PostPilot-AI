"""Typed payloads returned by LinkedIn OAuth and OIDC endpoints."""

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True, slots=True)
class LinkedInTokenResponse:
    access_token: str
    expires_in: int
    id_token: str
    scope: str
    token_type: str = "Bearer"  # noqa: S105


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
