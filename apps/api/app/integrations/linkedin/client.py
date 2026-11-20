"""HTTP client for LinkedIn OAuth token exchange and OIDC userinfo."""

from __future__ import annotations

from typing import Protocol
from urllib.parse import urlencode

import httpx
import structlog

from app.core.config import (
    LINKEDIN_AUTHORIZATION_URL,
    LINKEDIN_TOKEN_URL,
    LINKEDIN_USERINFO_URL,
    Settings,
)
from app.integrations.linkedin.errors import LinkedInTokenExchangeError, LinkedInUserInfoError
from app.integrations.linkedin.types import LinkedInTokenResponse, LinkedInUserInfo

logger = structlog.get_logger(__name__)


class LinkedInClient(Protocol):
    def build_authorization_url(self, *, state: str) -> str: ...

    async def exchange_code(self, *, code: str) -> LinkedInTokenResponse: ...

    async def fetch_userinfo(self, *, access_token: str) -> LinkedInUserInfo: ...


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
        # Never log `code` or the response body — they contain secrets.
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

        if response.status_code >= 400:
            logger.warning(
                "linkedin.token_exchange.failed",
                status_code=response.status_code,
            )
            raise LinkedInTokenExchangeError("LinkedIn rejected the authorization code exchange.")

        payload = response.json()
        access_token = payload.get("access_token")
        id_token = payload.get("id_token")
        expires_in = payload.get("expires_in")
        if (
            not isinstance(access_token, str)
            or not access_token
            or not isinstance(id_token, str)
            or not id_token
            or not isinstance(expires_in, int)
            or expires_in <= 0
        ):
            raise LinkedInTokenExchangeError("LinkedIn token response was missing required fields.")

        scope = payload.get("scope")
        if not isinstance(scope, str):
            scope = self._settings.linkedin_scopes

        logger.info("linkedin.token_exchange.succeeded")
        return LinkedInTokenResponse(
            access_token=access_token,
            expires_in=expires_in,
            id_token=id_token,
            scope=scope,
            token_type=str(payload.get("token_type") or "Bearer"),
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
