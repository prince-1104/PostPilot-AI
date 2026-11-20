"""Errors raised by the LinkedIn HTTP client and OIDC validator."""


class LinkedInIntegrationError(Exception):
    """Base class for LinkedIn integration failures that should not leak secrets."""

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class LinkedInTokenExchangeError(LinkedInIntegrationError):
    """Authorization-code exchange failed."""


class LinkedInIntrospectionError(LinkedInIntegrationError):
    """Token introspection failed or returned an unusable result."""


class LinkedInUserInfoError(LinkedInIntegrationError):
    """Userinfo request failed or returned an unexpected payload."""


class LinkedInOidcError(LinkedInIntegrationError):
    """ID token failed cryptographic or claim validation."""


class LinkedInScopeError(LinkedInIntegrationError):
    """Granted scopes could not be verified or do not meet requirements."""
