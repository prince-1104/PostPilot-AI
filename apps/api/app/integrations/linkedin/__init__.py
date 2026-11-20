"""LinkedIn OAuth and OIDC integration."""

from app.integrations.linkedin.client import HttpLinkedInClient, LinkedInClient
from app.integrations.linkedin.errors import (
    LinkedInIntegrationError,
    LinkedInOidcError,
    LinkedInTokenExchangeError,
    LinkedInUserInfoError,
)
from app.integrations.linkedin.oidc import LinkedInOidcValidator
from app.integrations.linkedin.types import (
    LinkedInTokenResponse,
    LinkedInUserInfo,
    ValidatedIdToken,
)

__all__ = [
    "HttpLinkedInClient",
    "LinkedInClient",
    "LinkedInIntegrationError",
    "LinkedInOidcError",
    "LinkedInOidcValidator",
    "LinkedInTokenExchangeError",
    "LinkedInTokenResponse",
    "LinkedInUserInfo",
    "LinkedInUserInfoError",
    "ValidatedIdToken",
]
