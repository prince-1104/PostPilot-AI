"""Secret redaction in structured logs."""

import json
import logging

import pytest
import structlog

from app.core.logging import REDACTED, configure_logging, redact_secrets

SECRET = "s3cr3t-value-that-must-never-be-logged"


def _redact(event: dict[str, object]) -> dict[str, object]:
    return dict(redact_secrets(None, "info", event))


@pytest.mark.parametrize(
    "key",
    [
        "password",
        "POSTGRES_PASSWORD",
        "client_secret",
        "access_token",
        "refresh_token",
        "token",
        "Authorization",
        "set-cookie",
        "api_key",
    ],
)
def test_values_under_sensitive_keys_are_redacted(key: str) -> None:
    assert _redact({"event": "login", key: SECRET}) == {"event": "login", key: REDACTED}


def test_nested_structures_are_redacted() -> None:
    event = {
        "event": "outbound_request",
        "headers": {"Authorization": f"Bearer {SECRET}", "Accept": "application/json"},
        "attempts": [{"refresh_token": SECRET, "status": 401}],
    }

    assert _redact(event) == {
        "event": "outbound_request",
        "headers": {"Authorization": REDACTED, "Accept": "application/json"},
        "attempts": [{"refresh_token": REDACTED, "status": 401}],
    }


def test_credentials_embedded_in_text_are_redacted() -> None:
    event = {
        "event": f"cannot connect to postgresql+asyncpg://postpilot:{SECRET}@db:5432/postpilot",
        "detail": f"upstream rejected header 'Authorization: Bearer {SECRET}'",
    }

    redacted = _redact(event)

    assert redacted == {
        "event": f"cannot connect to postgresql+asyncpg://postpilot:{REDACTED}@db:5432/postpilot",
        "detail": f"upstream rejected header 'Authorization: Bearer {REDACTED}'",
    }


def test_secret_query_parameters_are_redacted() -> None:
    event = {
        "event": (
            f"HTTP Request: GET https://app.example.com/callback?code={SECRET}&state=xyz "
            '"HTTP/1.1 200 OK"'
        ),
        "url": f"https://api.example.com/v1/me?fields=id&access_token={SECRET}",
    }

    assert _redact(event) == {
        "event": (
            f"HTTP Request: GET https://app.example.com/callback?code={REDACTED}&state=xyz "
            '"HTTP/1.1 200 OK"'
        ),
        "url": f"https://api.example.com/v1/me?fields=id&access_token={REDACTED}",
    }


def test_non_sensitive_values_are_left_untouched() -> None:
    event = {
        "event": "request.completed",
        "path": "/api/v1/health/live",
        "status_code": 200,
        "duration_ms": 1.25,
        "url": "https://api.linkedin.com/v2/userinfo?projection=full&page=2",
    }

    assert _redact(event) == event


def test_configured_loggers_emit_redacted_json(capsys: pytest.CaptureFixture[str]) -> None:
    configure_logging(level="INFO", log_format="json")

    with structlog.contextvars.bound_contextvars(request_id="req-123"):
        structlog.get_logger("test.structlog").info("token.exchange", client_secret=SECRET)
        # Standard-library loggers, as used by uvicorn and SQLAlchemy, share the pipeline.
        logging.getLogger("test.stdlib").warning("dsn=redis://default:%s@redis:6379/0", SECRET)
        try:
            raise RuntimeError(f"failed calling https://user:{SECRET}@example.com/hook")
        except RuntimeError:
            structlog.get_logger("test.structlog").exception("webhook.failed")

    output = capsys.readouterr().out
    records = [json.loads(line) for line in output.splitlines()]

    assert SECRET not in output
    assert [record["event"] for record in records] == [
        "token.exchange",
        f"dsn=redis://default:{REDACTED}@redis:6379/0",
        "webhook.failed",
    ]
    assert records[0]["client_secret"] == REDACTED
    assert f"https://user:{REDACTED}@example.com/hook" in records[2]["exception"]
    for record in records:
        assert record["request_id"] == "req-123"
        assert {"timestamp", "level", "logger"} <= set(record)
