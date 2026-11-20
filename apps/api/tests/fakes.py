"""Deterministic LinkedIn client doubles for OAuth tests."""

from __future__ import annotations

from app.integrations.linkedin import (
    LinkedInTokenExchangeError,
    LinkedInTokenResponse,
    LinkedInUserInfo,
    LinkedInUserInfoError,
)
from tests.conftest import LINKEDIN_REDIRECT_URI, LINKEDIN_SCOPES


class FakeLinkedInClient:
    def __init__(
        self,
        *,
        access_token: str = "li-access-token",  # noqa: S107
        id_token: str = "",
        scope: str = LINKEDIN_SCOPES,
        expires_in: int = 3600,
        userinfo: LinkedInUserInfo | None = None,
        exchange_error: Exception | None = None,
        userinfo_error: Exception | None = None,
    ) -> None:
        self.access_token = access_token
        self.id_token = id_token
        self.scope = scope
        self.expires_in = expires_in
        self.userinfo = userinfo or LinkedInUserInfo(
            sub="linkedin-sub-1",
            name="Ada Lovelace",
            email="ada@example.com",
            picture="https://example.com/ada.png",
        )
        self.exchange_error = exchange_error
        self.userinfo_error = userinfo_error
        self.last_state: str | None = None
        self.exchanged_codes: list[str] = []

    def build_authorization_url(self, *, state: str) -> str:
        self.last_state = state
        return (
            "https://www.linkedin.com/oauth/v2/authorization"
            f"?response_type=code&client_id=test-linkedin-client-id"
            f"&redirect_uri={LINKEDIN_REDIRECT_URI}&state={state}&scope={LINKEDIN_SCOPES}"
        )

    async def exchange_code(self, *, code: str) -> LinkedInTokenResponse:
        self.exchanged_codes.append(code)
        if self.exchange_error:
            raise self.exchange_error
        if not self.id_token:
            raise LinkedInTokenExchangeError("test misconfigured: id_token required")
        return LinkedInTokenResponse(
            access_token=self.access_token,
            expires_in=self.expires_in,
            id_token=self.id_token,
            scope=self.scope,
        )

    async def fetch_userinfo(self, *, access_token: str) -> LinkedInUserInfo:
        if self.userinfo_error:
            raise self.userinfo_error
        if access_token != self.access_token:
            raise LinkedInUserInfoError("unexpected access token")
        return self.userinfo
