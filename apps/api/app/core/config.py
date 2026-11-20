"""Environment-driven application configuration.

Settings are read only from process environment variables. Nothing is loaded from a
`.env` file implicitly: local commands opt in with `uv run --env-file ../../.env ...`
and containers receive their environment from Docker Compose.
"""

from functools import lru_cache
from typing import Annotated, Literal
from urllib.parse import urlsplit

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

Environment = Literal["local", "test", "staging", "production"]
LogLevel = Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]
LogFormat = Literal["json", "console"]


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

    @field_validator("postgres_password")
    @classmethod
    def _require_password(cls, value: SecretStr) -> SecretStr:
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
