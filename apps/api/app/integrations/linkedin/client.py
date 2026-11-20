"""HTTP client for LinkedIn OAuth token exchange, introspection, and OIDC userinfo."""

from __future__ import annotations

from typing import Any, Protocol
from urllib.parse import urlencode

import httpx
import structlog

from app.core.config import (
    LINKEDIN_AUTHORIZATION_URL,
    LINKEDIN_INTROSPECT_URL,
    LINKEDIN_TOKEN_URL,
    LINKEDIN_USERINFO_URL,
    Settings,
)
from app.integrations.linkedin.errors import (
    LinkedInIntrospectionError,
    LinkedInTokenExchangeError,
    LinkedInUserInfoError,
)
from app.integrations.linkedin.types import (
    LinkedInTokenIntrospection,
    LinkedInTokenResponse,
    LinkedInUserInfo,
)

logger = structlog.get_logger(__name__)


class LinkedInClient(Protocol):
    def build_authorization_url(self, *, state: str) -> str: ...

    async def exchange_code(self, *, code: str) -> LinkedInTokenResponse: ...

    async def introspect_token(self, *, access_token: str) -> LinkedInTokenIntrospection: ...

    async def fetch_userinfo(self, *, access_token: str) -> LinkedInUserInfo: ...


def _sanitized_payload_diagnostics(payload: object) -> dict[str, object]:
    """Describe a JSON body without logging secrets or PII values.

    Key names avoid substrings like ``access_token`` so the log redactor does not
    replace boolean presence flags with ``[REDACTED]``.
    """
    if not isinstance(payload, dict):
        return {"payload_type": type(payload).__name__}
    keys = sorted(str(key) for key in payload)
    diagnostics: dict[str, object] = {
        "response_keys": keys,
        "ak_field": "access_token" in payload,
        "ik_field": "id_token" in payload,
        "rk_field": "refresh_token" in payload,
        "scope_field": "scope" in payload,
        "expires_in_field": "expires_in" in payload,
    }
    scope = payload.get("scope") if "scope" in payload else None
    if "scope" in payload:
        diagnostics["scope_type"] = type(scope).__name__
        if isinstance(scope, str):
            diagnostics["scope_empty"] = scope.strip() == ""
            diagnostics["scope_char_len"] = len(scope)
            # Delimiter shape only — never the raw value (may be unexpected).
            diagnostics["scope_has_comma"] = "," in scope
            diagnostics["scope_has_space"] = any(ch.isspace() for ch in scope)
            diagnostics["scope_has_pct"] = "%" in scope
    expires_in = payload.get("expires_in")
    if "expires_in" in payload:
        diagnostics["expires_in_type"] = type(expires_in).__name__
    return diagnostics


class HttpLinkedInClient:
    """Talks to LinkedIn over HTTPX with explicit timeouts."""

    def __init__(self, settings: Settings, *, http_client: httpx.AsyncClient | None = None) -> None:
        self._settings = settings
        self._owns_client = http_client is None
        timeout = httpx.Timeout(settings.linkedin_http_timeout_seconds)
        self._http = http_client or httpx.AsyncClient(timeout=timeout)

    async def aclose(self) -> None:
        if self._owns_client:
            await self._http.aclose()

    def build_authorization_url(self, *, state: str) -> str:
        # urlencode turns spaces in scopes into %20 (space-delimited, URL-encoded).
        query = urlencode(
            {
                "response_type": "code",
                "client_id": self._settings.linkedin_client_id,
                "redirect_uri": self._settings.linkedin_redirect_uri,
                "state": state,
                "scope": self._settings.linkedin_scopes,
            }
        )
        return f"{LINKEDIN_AUTHORIZATION_URL}?{query}"

    async def exchange_code(self, *, code: str) -> LinkedInTokenResponse:
        # Never log `code` or secret-bearing response values.
        logger.info("linkedin.token_exchange.start")
        try:
            response = await self._http.post(
                LINKEDIN_TOKEN_URL,
                data={
                    "grant_type": "authorization_code",
                    "code": code,
                    "redirect_uri": self._settings.linkedin_redirect_uri,
                    "client_id": self._settings.linkedin_client_id,
                    "client_secret": self._settings.linkedin_client_secret.get_secret_value(),
                },
                headers={"Accept": "application/json"},
            )
        except httpx.HTTPError as exc:
            raise LinkedInTokenExchangeError(
                "Could not reach LinkedIn to exchange the authorization code."
            ) from exc

        payload: Any
        try:
            payload = response.json()
        except ValueError:
            payload = None

        if response.status_code >= 400:
            logger.warning(
                "linkedin.token_exchange.failed",
                status_code=response.status_code,
                **_sanitized_payload_diagnostics(payload),
            )
            raise LinkedInTokenExchangeError("LinkedIn rejected the authorization code exchange.")

        if not isinstance(payload, dict):
            logger.warning(
                "linkedin.token_exchange.malformed",
                status_code=response.status_code,
                payload_type=type(payload).__name__,
            )
            raise LinkedInTokenExchangeError("LinkedIn token response was not valid JSON.")

        logger.info(
            "linkedin.token_exchange.succeeded",
            status_code=response.status_code,
            **_sanitized_payload_diagnostics(payload),
        )

        access_token = payload.get("access_token")
        id_token = payload.get("id_token")
        expires_in = payload.get("expires_in")
        if isinstance(expires_in, str) and expires_in.isdigit():
            expires_in = int(expires_in)
        if (
            not isinstance(access_token, str)
            or not access_token
            or not isinstance(id_token, str)
            or not id_token
            or not isinstance(expires_in, int)
            or expires_in <= 0
        ):
            raise LinkedInTokenExchangeError("LinkedIn token response was missing required fields.")

        # Preserve absence vs empty string vs present value. Do not invent granted scopes.
        if "scope" not in payload:
            scope: str | None = None
        else:
            raw_scope = payload.get("scope")
            if raw_scope is None:
                scope = None
            elif isinstance(raw_scope, str):
                scope = raw_scope
            else:
                logger.warning(
                    "linkedin.token_exchange.scope_wrong_type",
                    scope_type=type(raw_scope).__name__,
                )
                raise LinkedInTokenExchangeError(
                    "LinkedIn token response contained a malformed scope field."
                )

        return LinkedInTokenResponse(
            access_token=access_token,
            expires_in=expires_in,
            id_token=id_token,
            scope=scope,
            token_type=str(payload.get("token_type") or "Bearer"),
        )

    async def introspect_token(self, *, access_token: str) -> LinkedInTokenIntrospection:
        logger.info("linkedin.introspect.start")
        try:
            response = await self._http.post(
                LINKEDIN_INTROSPECT_URL,
                data={
                    "client_id": self._settings.linkedin_client_id,
                    "client_secret": self._settings.linkedin_client_secret.get_secret_value(),
                    "token": access_token,
                },
                headers={"Accept": "application/json"},
            )
        except httpx.HTTPError as exc:
            raise LinkedInIntrospectionError(
                "Could not reach LinkedIn to introspect the access token."
            ) from exc

        payload: Any
        try:
            payload = response.json()
        except ValueError:
            payload = None

        if response.status_code >= 400:
            logger.warning(
                "linkedin.introspect.failed",
                status_code=response.status_code,
                **_sanitized_payload_diagnostics(payload),
            )
            raise LinkedInIntrospectionError("LinkedIn rejected the token introspection request.")

        if not isinstance(payload, dict):
            logger.warning(
                "linkedin.introspect.malformed",
                status_code=response.status_code,
                payload_type=type(payload).__name__,
            )
            raise LinkedInIntrospectionError("LinkedIn introspection response was not valid JSON.")

        logger.info(
            "linkedin.introspect.succeeded",
            status_code=response.status_code,
            **_sanitized_payload_diagnostics(payload),
            active=payload.get("active") if isinstance(payload.get("active"), bool) else None,
            has_client_id="client_id" in payload,
        )

        active = payload.get("active")
        if not isinstance(active, bool):
            raise LinkedInIntrospectionError(
                "LinkedIn introspection response was missing an active flag."
            )

        client_id = payload.get("client_id")
        if client_id is not None and not isinstance(client_id, str):
            raise LinkedInIntrospectionError(
                "LinkedIn introspection response contained a malformed client_id."
            )

        if "scope" not in payload:
            scope: str | None = None
        else:
            raw_scope = payload.get("scope")
            if raw_scope is None:
                scope = None
            elif isinstance(raw_scope, str):
                scope = raw_scope
            else:
                raise LinkedInIntrospectionError(
                    "LinkedIn introspection response contained a malformed scope field."
                )

        status = payload.get("status")
        return LinkedInTokenIntrospection(
            active=active,
            client_id=client_id if isinstance(client_id, str) else None,
            scope=scope,
            status=status if isinstance(status, str) else None,
        )

    async def fetch_userinfo(self, *, access_token: str) -> LinkedInUserInfo:
        logger.info("linkedin.userinfo.start")
        try:
            response = await self._http.get(
                LINKEDIN_USERINFO_URL,
                headers={
                    "Authorization": f"Bearer {access_token}",
                    "Accept": "application/json",
                },
            )
        except httpx.HTTPError as exc:
            raise LinkedInUserInfoError("Could not reach LinkedIn userinfo.") from exc

        if response.status_code >= 400:
            logger.warning("linkedin.userinfo.failed", status_code=response.status_code)
            raise LinkedInUserInfoError("LinkedIn userinfo request failed.")

        payload = response.json()
        sub = payload.get("sub")
        name = payload.get("name") or payload.get("given_name") or ""
        if not isinstance(sub, str) or not sub:
            raise LinkedInUserInfoError("LinkedIn userinfo did not include a subject.")
        if not isinstance(name, str) or not name.strip():
            name = "LinkedIn member"

        email = payload.get("email")
        picture = payload.get("picture")
        logger.info("linkedin.userinfo.succeeded")
        return LinkedInUserInfo(
            sub=sub,
            name=name.strip(),
            email=email if isinstance(email, str) else None,
            picture=picture if isinstance(picture, str) else None,
        )
