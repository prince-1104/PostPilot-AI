"""Configuration loading and validation."""

import base64
import secrets

import pytest
from pydantic import ValidationError

from app.core.config import Settings
from app.db.session import build_database_url
from tests.conftest import SettingsFactory

REQUIRED_ENVIRONMENT = {
    "APP_ENV": "local",
    "POSTGRES_HOST": "db.internal",
    "POSTGRES_DB": "postpilot",
    "POSTGRES_USER": "postpilot",
    "POSTGRES_PASSWORD": "value-used-only-in-this-test",
    "CORS_ALLOWED_ORIGINS": "http://localhost:3000",
    "LINKEDIN_CLIENT_ID": "linkedin-client",
    "LINKEDIN_CLIENT_SECRET": "linkedin-secret",
    "LINKEDIN_REDIRECT_URI": "http://localhost:8000/api/v1/auth/linkedin/callback",
    "LINKEDIN_SCOPES": "openid profile email w_member_social",
    "TOKEN_ENCRYPTION_KEY": base64.b64encode(secrets.token_bytes(32)).decode(),
    "WEB_BASE_URL": "http://localhost:3000",
}


def _set_environment(monkeypatch: pytest.MonkeyPatch, **overrides: str) -> None:
    for name, value in {**REQUIRED_ENVIRONMENT, **overrides}.items():
        monkeypatch.setenv(name, value)


def test_settings_load_from_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_environment(
        monkeypatch,
        POSTGRES_PORT="6543",
        CORS_ALLOWED_ORIGINS="http://localhost:3000, https://app.example.com",
        COOKIE_SECURE="false",
        SESSION_TTL_SECONDS="7200",
    )

    settings = Settings()

    assert settings.app_env == "local"
    assert settings.postgres_host == "db.internal"
    assert settings.postgres_port == 6543
    assert settings.cors_allowed_origins == ["http://localhost:3000", "https://app.example.com"]
    assert settings.linkedin_client_id == "linkedin-client"
    assert settings.web_base_url == "http://localhost:3000"
    assert settings.cookie_secure is False
    assert settings.session_ttl_seconds == 7200
    # Operational tunables fall back to documented defaults.
    assert settings.log_level == "INFO"
    assert settings.log_format == "json"


@pytest.mark.parametrize("missing", sorted(REQUIRED_ENVIRONMENT))
def test_missing_required_variable_is_rejected(
    monkeypatch: pytest.MonkeyPatch, missing: str
) -> None:
    _set_environment(monkeypatch)
    monkeypatch.delenv(missing)

    with pytest.raises(ValidationError) as exc_info:
        Settings()

    assert [error["loc"] for error in exc_info.value.errors()] == [(missing.lower(),)]


def test_empty_database_password_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_environment(monkeypatch, POSTGRES_PASSWORD="")

    with pytest.raises(ValidationError, match="must not be empty"):
        Settings()


@pytest.mark.parametrize("origin", ["*", "https://*.example.com"])
def test_wildcard_cors_origin_is_rejected(settings_factory: SettingsFactory, origin: str) -> None:
    with pytest.raises(ValidationError, match="wildcard origin"):
        settings_factory(cors_allowed_origins=[origin])


@pytest.mark.parametrize(
    "origin",
    [
        "http://localhost:3000/",
        "https://app.example.com/dashboard",
        "https://app.example.com?debug=1",
        "https://user@app.example.com",
        "ftp://app.example.com",
        "app.example.com",
    ],
)
def test_malformed_cors_origin_is_rejected(settings_factory: SettingsFactory, origin: str) -> None:
    with pytest.raises(ValidationError, match="is not a valid origin"):
        settings_factory(cors_allowed_origins=[origin])


def test_duplicate_cors_origins_are_collapsed(settings_factory: SettingsFactory) -> None:
    settings = settings_factory(
        cors_allowed_origins=["http://localhost:3000", "http://localhost:3000"]
    )

    assert settings.cors_allowed_origins == ["http://localhost:3000"]


@pytest.mark.parametrize(
    "overrides",
    [
        {"app_env": "development"},
        {"log_level": "VERBOSE"},
        {"log_format": "xml"},
        {"postgres_port": 0},
        {"postgres_port": 70000},
        {"db_pool_size": 0},
        {"readiness_timeout_seconds": 0},
    ],
)
def test_out_of_range_values_are_rejected(
    settings_factory: SettingsFactory, overrides: dict[str, object]
) -> None:
    with pytest.raises(ValidationError):
        settings_factory(**overrides)


def test_database_password_is_not_exposed_when_settings_are_printed(
    settings_factory: SettingsFactory,
) -> None:
    password = "value-that-must-not-be-printed"
    settings = settings_factory(postgres_password=password)

    assert password not in repr(settings)
    assert password not in str(settings)
    assert password not in str(build_database_url(settings))


def test_database_url_escapes_special_characters_in_credentials(
    settings_factory: SettingsFactory,
) -> None:
    password = "p@ss:w/rd#1"
    settings = settings_factory(
        postgres_host="db.internal",
        postgres_port=5432,
        postgres_db="postpilot",
        postgres_user="postpilot",
        postgres_password=password,
    )

    url = build_database_url(settings)

    assert url.drivername == "postgresql+asyncpg"
    assert url.password == password
    assert url.render_as_string(hide_password=False) == (
        "postgresql+asyncpg://postpilot:p%40ss%3Aw%2Frd%231@db.internal:5432/postpilot"
    )


def test_missing_required_linkedin_scope_is_rejected(settings_factory: SettingsFactory) -> None:
    with pytest.raises(ValidationError, match="missing required scopes"):
        settings_factory(linkedin_scopes="openid profile email")


def test_production_requires_secure_cookies(settings_factory: SettingsFactory) -> None:
    with pytest.raises(ValidationError, match="COOKIE_SECURE"):
        settings_factory(app_env="production", cookie_secure=False)
