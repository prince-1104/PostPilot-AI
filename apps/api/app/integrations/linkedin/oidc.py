"""Validate LinkedIn OIDC ID tokens against JWKS."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Protocol

import httpx
import jwt
from jwt import PyJWKClient

from app.core.config import LINKEDIN_ISSUERS, LINKEDIN_JWKS_URL
from app.integrations.linkedin.errors import LinkedInOidcError
from app.integrations.linkedin.types import ValidatedIdToken


class JwksProvider(Protocol):
    def get_signing_key_from_jwt(self, token: str) -> Any: ...


class LinkedInOidcValidator:
    """Verifies signature, issuer, audience, and expiration of LinkedIn ID tokens."""

    def __init__(
        self,
        *,
        client_id: str,
        jwks_url: str = LINKEDIN_JWKS_URL,
        issuers: frozenset[str] = LINKEDIN_ISSUERS,
        jwks_client: JwksProvider | None = None,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        self._client_id = client_id
        self._issuers = issuers
        self._jwks_client = jwks_client or PyJWKClient(jwks_url, cache_keys=True)
        # Kept so tests can inject a client; PyJWKClient uses urllib by default.
        self._http_client = http_client

    def validate_id_token(self, id_token: str) -> ValidatedIdToken:
        try:
            signing_key = self._jwks_client.get_signing_key_from_jwt(id_token)
            claims = jwt.decode(
                id_token,
                signing_key.key,
                algorithms=["RS256"],
                audience=self._client_id,
                options={
                    "require": ["exp", "iat", "iss", "sub", "aud"],
                    "verify_iss": False,  # we accept either historical LinkedIn issuer
                },
            )
        except LinkedInOidcError:
            raise
        except Exception as exc:
            raise LinkedInOidcError("LinkedIn ID token validation failed.") from exc

        issuer = claims.get("iss")
        if issuer not in self._issuers:
            raise LinkedInOidcError("LinkedIn ID token issuer is not trusted.")

        subject = claims.get("sub")
        if not isinstance(subject, str) or not subject:
            raise LinkedInOidcError("LinkedIn ID token is missing a subject.")

        audience = claims.get("aud")
        if isinstance(audience, list):
            if self._client_id not in audience:
                raise LinkedInOidcError("LinkedIn ID token audience mismatch.")
            audience_value = audience[0]
        elif audience != self._client_id:
            raise LinkedInOidcError("LinkedIn ID token audience mismatch.")
        else:
            audience_value = audience

        exp = claims["exp"]
        return ValidatedIdToken(
            subject=subject,
            issuer=str(issuer),
            audience=str(audience_value),
            expires_at=datetime.fromtimestamp(int(exp), tz=UTC),
        )
