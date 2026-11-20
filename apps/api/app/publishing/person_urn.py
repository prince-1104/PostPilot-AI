"""Resolve LinkedIn person author URNs from stored OIDC identity.

With Sign In with LinkedIn (OpenID Connect), the userinfo ``sub`` claim is the
member identifier used to construct ``urn:li:person:{sub}``. This avoids the
restricted ``/v2/me`` endpoint. Organization URNs are never accepted.
"""

from __future__ import annotations

import re

_SUBJECT_RE = re.compile(r"^[A-Za-z0-9._\-]{1,128}$")
_PERSON_URN_RE = re.compile(r"^urn:li:person:([A-Za-z0-9._\-]{1,128})$")
_POST_URN_RE = re.compile(r"^urn:li:(share|ugcPost):\d+$")


class PersonUrnError(ValueError):
    """Raised when a stored subject cannot form a valid person URN."""


def person_urn_from_oidc_subject(subject: str) -> str:
    """Map an OIDC ``sub`` to ``urn:li:person:{sub}``."""
    cleaned = subject.strip()
    if not cleaned:
        raise PersonUrnError("LinkedIn identity subject is empty.")
    if cleaned.startswith("urn:li:organization:"):
        raise PersonUrnError("Organization URNs cannot author member posts.")
    if cleaned.startswith("urn:li:person:"):
        match = _PERSON_URN_RE.fullmatch(cleaned)
        if not match:
            raise PersonUrnError("Stored person URN is malformed.")
        return cleaned
    if not _SUBJECT_RE.fullmatch(cleaned):
        raise PersonUrnError("LinkedIn identity subject has an unsupported format.")
    return f"urn:li:person:{cleaned}"


def validate_post_urn(value: str) -> str:
    """Accept only share or ugcPost URNs returned by the Posts API."""
    cleaned = value.strip()
    if not _POST_URN_RE.fullmatch(cleaned):
        raise ValueError("LinkedIn response did not include a valid post URN.")
    return cleaned


def linkedin_permalink_for_post_urn(urn: str) -> str | None:
    """Build a member-facing permalink when the URN type is recognized."""
    try:
        validated = validate_post_urn(urn)
    except ValueError:
        return None
    # LinkedIn serves activity/share and ugcPost deep links via updateUrn encoding.
    from urllib.parse import quote

    return f"https://www.linkedin.com/feed/update/{quote(validated, safe='')}"
