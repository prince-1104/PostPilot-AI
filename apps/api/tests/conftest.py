"""Shared test fixtures.

Unit tests never read the developer's environment: every Settings-related variable is
removed first, and settings are built from explicit values. The database settings
point at a closed local port, so any accidental database access fails fast.
"""

import io
import logging
import secrets
from collections.abc import AsyncIterator, Callable

import httpx
import pytest
import structlog
from fastapi import FastAPI

from app.core.config import Settings
from app.main import create_app

ALLOWED_ORIGIN = "http://localhost:3000"

SettingsFactory = Callable[..., Settings]


@pytest.fixture(autouse=True)
def _isolate_environment(request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch) -> None:
    """Remove ambient configuration so unit tests are deterministic."""
    if request.node.get_closest_marker("integration"):
        return
    for field_name in Settings.model_fields:
        monkeypatch.delenv(field_name.upper(), raising=False)


@pytest.fixture
def settings_factory(unused_tcp_port: int) -> SettingsFactory:
    """Build valid settings, with keyword overrides for the case under test."""

    def factory(**overrides: object) -> Settings:
        values: dict[str, object] = {
            "app_env": "test",
            "log_format": "json",
            "postgres_host": "127.0.0.1",
            # Nothing listens here, so connection attempts are refused.
            "postgres_port": unused_tcp_port,
            "postgres_db": "postpilot_test",
            "postgres_user": "postpilot_test",
            "postgres_password": secrets.token_hex(16),
            "db_connect_timeout_seconds": 1.0,
            "readiness_timeout_seconds": 2.0,
            "cors_allowed_origins": [ALLOWED_ORIGIN],
        }
        values.update(overrides)
        return Settings(**values)

    return factory


@pytest.fixture
def settings(settings_factory: SettingsFactory) -> Settings:
    return settings_factory()


@pytest.fixture
def app(settings: Settings) -> FastAPI:
    return create_app(settings)


@pytest.fixture
def log_output(app: FastAPI) -> io.StringIO:
    """Redirect the application's log handler to a buffer the test can read.

    `capsys` cannot be used for this: pytest swaps its stream between the setup and
    call phases, while the handler is bound to a stream when the app is created.
    """
    buffer = io.StringIO()
    app_handlers = [
        handler
        for handler in logging.getLogger().handlers
        if isinstance(handler, logging.StreamHandler)
        and isinstance(handler.formatter, structlog.stdlib.ProcessorFormatter)
    ]
    assert len(app_handlers) == 1, "expected exactly one application log handler"
    app_handlers[0].setStream(buffer)
    return buffer


@pytest.fixture
async def client(app: FastAPI) -> AsyncIterator[httpx.AsyncClient]:
    """HTTP client bound to the app in-process, with startup and shutdown executed."""
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            yield client
