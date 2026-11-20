"""Parse LinkedIn scope strings without conflating response formats.

- Token exchange (`/oauth/v2/accessToken`): space-delimited, may be URL-encoded.
- Token introspection (`/oauth/v2/introspectToken`): comma-delimited.
"""

from __future__ import annotations

from urllib.parse import unquote


def parse_token_exchange_scopes(raw: str) -> frozenset[str]:
    """Parse the `scope` field from an authorization-code token response."""
    decoded = unquote(raw.strip())
    return frozenset(part for part in decoded.split() if part)


def parse_introspection_scopes(raw: str) -> frozenset[str]:
    """Parse the `scope` field from an introspectToken response."""
    return frozenset(part.strip() for part in raw.split(",") if part.strip())


def format_granted_scopes(scopes: frozenset[str]) -> str:
    """Stable space-delimited form for storage and API responses."""
    return " ".join(sorted(scopes))
