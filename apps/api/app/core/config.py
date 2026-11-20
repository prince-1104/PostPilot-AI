"""Environment-driven application configuration.

Settings are read only from process environment variables. Nothing is loaded from a
`.env` file implicitly: local commands opt in with `uv run --env-file ../../.env ...`
and containers receive their environment from Docker Compose.
"""

from functools import lru_cache
from typing import Annotated, Literal
from urllib.parse import urlsplit

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

Environment = Literal["local", "test", "staging", "production"]
LogLevel = Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]
LogFormat = Literal["json", "console"]

# Scopes PostPilot needs for sign-in and (later) publishing. Configuration that omits
# any of these fails at startup so we never silently degrade authentication.
REQUIRED_LINKEDIN_SCOPES: frozenset[str] = frozenset(
    {"openid", "profile", "email", "w_member_social"}
)

LINKEDIN_AUTHORIZATION_URL = "https://www.linkedin.com/oauth/v2/authorization"
LINKEDIN_TOKEN_URL = "https://www.linkedin.com/oauth/v2/accessToken"  # noqa: S105
LINKEDIN_INTROSPECT_URL = "https://www.linkedin.com/oauth/v2/introspectToken"
LINKEDIN_USERINFO_URL = "https://api.linkedin.com/v2/userinfo"
LINKEDIN_JWKS_URL = "https://www.linkedin.com/oauth/openid/jwks"
# LinkedIn has used both issuer values; accept either when validating ID tokens.
LINKEDIN_ISSUERS: frozenset[str] = frozenset(
    {"https://www.linkedin.com", "https://www.linkedin.com/oauth"}
)


class Settings(BaseSettings):
    """Typed application settings.

    Connection identity and credentials have no defaults, so a missing or empty value
    fails at startup instead of falling back to a guessable credential.
    """

    model_config = SettingsConfigDict(extra="ignore", frozen=True)

    app_env: Environment
    log_level: LogLevel = "INFO"
    log_format: LogFormat = "json"

    postgres_host: str = Field(min_length=1)
    postgres_port: int = Field(default=5432, ge=1, le=65535)
    postgres_db: str = Field(min_length=1)
    postgres_user: str = Field(min_length=1)
    postgres_password: SecretStr

    db_pool_size: int = Field(default=5, ge=1)
    db_max_overflow: int = Field(default=10, ge=0)
    db_connect_timeout_seconds: float = Field(default=5.0, gt=0)
    readiness_timeout_seconds: float = Field(default=3.0, gt=0)

    # Comma-separated list of browser origins, e.g. "http://localhost:3000,https://app.example.com".
    # NoDecode stops pydantic-settings from requiring JSON for this list.
    cors_allowed_origins: Annotated[list[str], NoDecode]

    linkedin_client_id: str = Field(min_length=1)
    linkedin_client_secret: SecretStr
    linkedin_redirect_uri: str = Field(min_length=1)
    # Space-separated OAuth scopes. Must include every entry in REQUIRED_LINKEDIN_SCOPES.
    linkedin_scopes: str = Field(min_length=1)

    # Base64-encoded 32-byte AES-256 key used to encrypt LinkedIn access tokens at rest.
    token_encryption_key: SecretStr

    # Frontend origin used for post-OAuth redirects (scheme://host[:port], no path).
    web_base_url: str = Field(min_length=1)

    # Session cookie Secure flag. False only for local HTTP; must be True in production.
    cookie_secure: bool = False
    session_ttl_seconds: int = Field(default=60 * 60 * 24 * 14, ge=60, le=60 * 60 * 24 * 90)
    oauth_state_ttl_seconds: int = Field(default=600, ge=60, le=3600)
    linkedin_http_timeout_seconds: float = Field(default=10.0, gt=0, le=60)

    # Minimum lead time before a post may be scheduled (avoids near-immediate races).
    # Documented default: 60 seconds.
    schedule_min_lead_seconds: int = Field(default=60, ge=0, le=3600)
    # LinkedIn UGC/share text posts accept up to 3000 characters of commentary.
    post_content_max_length: int = Field(default=3000, ge=1, le=10000)
    posts_page_size_default: int = Field(default=20, ge=1, le=100)
    posts_page_size_max: int = Field(default=50, ge=1, le=100)

    @field_validator("postgres_password", "linkedin_client_secret", "token_encryption_key")
    @classmethod
    def _require_secret(cls, value: SecretStr) -> SecretStr:
        if not value.get_secret_value():
            raise ValueError("must not be empty")
        return value

    @field_validator("cors_allowed_origins", mode="before")
    @classmethod
    def _split_origins(cls, value: object) -> object:
        if isinstance(value, str):
            return [item.strip() for item in value.split(",") if item.strip()]
        return value

    @field_validator("cors_allowed_origins")
    @classmethod
    def _validate_origins(cls, origins: list[str]) -> list[str]:
        for origin in origins:
            _validate_origin(origin)
        return list(dict.fromkeys(origins))

    @field_validator("web_base_url")
    @classmethod
    def _validate_web_base_url(cls, value: str) -> str:
        _validate_origin(value.rstrip("/"))
        return value.rstrip("/")

    @field_validator("linkedin_redirect_uri")
    @classmethod
    def _validate_redirect_uri(cls, value: str) -> str:
        parts = urlsplit(value)
        if parts.scheme not in {"http", "https"} or not parts.hostname or parts.fragment:
            raise ValueError(
                "must be an absolute http(s) URL without a fragment "
                "(e.g. http://localhost:8000/api/v1/auth/linkedin/callback)"
            )
        return value

    @field_validator("linkedin_scopes")
    @classmethod
    def _validate_scopes(cls, value: str) -> str:
        scopes = [part for part in value.split() if part]
        if not scopes:
            raise ValueError("must list at least one scope")
        missing = sorted(REQUIRED_LINKEDIN_SCOPES - set(scopes))
        if missing:
            raise ValueError(
                "LINKEDIN_SCOPES is missing required scopes: "
                f"{', '.join(missing)}. Provision them on the LinkedIn developer app "
                "and include them in LINKEDIN_SCOPES; do not silently drop scopes."
            )
        # Preserve order while deduplicating.
        return " ".join(dict.fromkeys(scopes))

    @model_validator(mode="after")
    def _validate_cookie_secure_for_production(self) -> Settings:
        if self.app_env == "production" and not self.cookie_secure:
            raise ValueError("COOKIE_SECURE must be true when APP_ENV=production")
        return self

    @property
    def linkedin_scope_list(self) -> list[str]:
        return self.linkedin_scopes.split()


def _validate_origin(origin: str) -> None:
    """Reject anything that is not an exact `scheme://host[:port]` browser origin.

    Wildcards are refused outright because the API sends CORS responses with
    credentials enabled, and a wildcard origin must never be combined with that.
    """
    if "*" in origin:
        raise ValueError(f"wildcard origin {origin!r} is not allowed; list each origin explicitly")

    parts = urlsplit(origin)
    is_exact_origin = (
        parts.scheme in {"http", "https"}
        and bool(parts.hostname)
        and parts.username is None
        and parts.password is None
        and not parts.path
        and not parts.query
        and not parts.fragment
    )
    if not is_exact_origin:
        raise ValueError(
            f"{origin!r} is not a valid origin; expected scheme://host[:port] "
            "with no path or trailing slash"
        )


@lru_cache
def get_settings() -> Settings:
    """Return the process-wide settings, validated once on first use."""
    return Settings()
