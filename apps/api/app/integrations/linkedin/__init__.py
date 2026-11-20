"""LinkedIn OAuth and OIDC integration."""

from app.integrations.linkedin.client import HttpLinkedInClient, LinkedInClient
from app.integrations.linkedin.errors import (
    LinkedInIntegrationError,
    LinkedInIntrospectionError,
    LinkedInOidcError,
    LinkedInScopeError,
    LinkedInTokenExchangeError,
    LinkedInUserInfoError,
)
from app.integrations.linkedin.oidc import LinkedInOidcValidator
from app.integrations.linkedin.scopes import (
    format_granted_scopes,
    parse_introspection_scopes,
    parse_token_exchange_scopes,
)
from app.integrations.linkedin.types import (
    LinkedInTokenIntrospection,
    LinkedInTokenResponse,
    LinkedInUserInfo,
    ValidatedIdToken,
)

__all__ = [
    "HttpLinkedInClient",
    "LinkedInClient",
    "LinkedInIntegrationError",
    "LinkedInIntrospectionError",
    "LinkedInOidcError",
    "LinkedInOidcValidator",
    "LinkedInScopeError",
    "LinkedInTokenExchangeError",
    "LinkedInTokenIntrospection",
    "LinkedInTokenResponse",
    "LinkedInUserInfo",
    "LinkedInUserInfoError",
    "ValidatedIdToken",
    "format_granted_scopes",
    "parse_introspection_scopes",
    "parse_token_exchange_scopes",
]
