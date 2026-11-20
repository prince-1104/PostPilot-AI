"""Structured logging with request correlation and secret redaction.

Both structlog loggers and standard-library loggers (uvicorn, SQLAlchemy, Alembic) are
rendered by the same formatter, so every log line passes through `redact_secrets`.
"""

import logging
import re
import sys
from collections.abc import Mapping

import structlog
from structlog.types import EventDict, Processor, WrappedLogger

REDACTED = "[REDACTED]"

_SENSITIVE_KEY_FRAGMENTS = (
    "password",
    "passwd",
    "secret",
    "authorization",
    "cookie",
    "api_key",
    "apikey",
    "private_key",
    "credential",
    "access_token",
    "refresh_token",
    "id_token",
)

# scheme://user:password@host -> scheme://user:[REDACTED]@host
_URL_CREDENTIALS = re.compile(
    r"(?P<prefix>[a-z][a-z0-9+.\-]*://[^/\s:@]*):(?P<secret>[^/\s@]+)@",
    re.IGNORECASE,
)
# "Bearer <token>" as it appears in Authorization headers.
_BEARER_TOKEN = re.compile(r"\b(?P<scheme>Bearer)\s+[A-Za-z0-9._~+/=\-]{16,}", re.IGNORECASE)
# ?code=<value> and similar query parameters. HTTP client libraries log full request
# URLs, which is how OAuth authorization codes and tokens typically end up in logs.
_QUERY_SECRET = re.compile(
    r"(?P<prefix>[?&](?:code|token|access_token|refresh_token|id_token|client_secret"
    r"|password|api_key|apikey)=)[^&#\s\"']+",
    re.IGNORECASE,
)


def _is_sensitive_key(key: object) -> bool:
    if not isinstance(key, str):
        return False
    normalized = key.lower().replace("-", "_")
    if normalized == "token" or normalized.endswith("_token"):
        return True
    return any(fragment in normalized for fragment in _SENSITIVE_KEY_FRAGMENTS)


def _scrub(value: object) -> object:
    """Recursively redact sensitive keys and credential-shaped substrings."""
    if isinstance(value, str):
        scrubbed = _URL_CREDENTIALS.sub(rf"\g<prefix>:{REDACTED}@", value)
        scrubbed = _BEARER_TOKEN.sub(rf"\g<scheme> {REDACTED}", scrubbed)
        return _QUERY_SECRET.sub(rf"\g<prefix>{REDACTED}", scrubbed)
    if isinstance(value, Mapping):
        return {
            key: REDACTED if _is_sensitive_key(key) else _scrub(item) for key, item in value.items()
        }
    if isinstance(value, list | tuple | set | frozenset):
        return [_scrub(item) for item in value]
    return value


def redact_secrets(_logger: WrappedLogger, _method_name: str, event_dict: EventDict) -> EventDict:
    """structlog processor that removes secrets before a log line is rendered."""
    return {
        key: REDACTED if _is_sensitive_key(key) else _scrub(value)
        for key, value in event_dict.items()
    }


def configure_logging(*, level: str, log_format: str) -> None:
    """Route all logging through one redacting, structured handler on stdout."""
    shared_processors: list[Processor] = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        structlog.processors.StackInfoRenderer(),
    ]

    structlog.configure(
        processors=[
            *shared_processors,
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )

    renderer: Processor = (
        structlog.processors.JSONRenderer()
        if log_format == "json"
        else structlog.dev.ConsoleRenderer()
    )
    formatter = structlog.stdlib.ProcessorFormatter(
        # Applied to records from standard-library loggers before the final chain.
        foreign_pre_chain=[*shared_processors, structlog.stdlib.ExtraAdder()],
        processors=[
            structlog.stdlib.ProcessorFormatter.remove_processors_meta,
            # Render tracebacks to text first so redaction also covers them.
            structlog.processors.format_exc_info,
            redact_secrets,
            renderer,
        ],
    )

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(formatter)

    root_logger = logging.getLogger()
    root_logger.handlers.clear()
    root_logger.addHandler(handler)
    root_logger.setLevel(level)

    # uvicorn installs its own handlers before the application is imported. Remove
    # them so its records propagate to the root handler configured above.
    for name in ("uvicorn", "uvicorn.error"):
        uvicorn_logger = logging.getLogger(name)
        uvicorn_logger.handlers.clear()
        uvicorn_logger.propagate = True

    # RequestContextMiddleware emits one structured log line per request, so uvicorn's
    # plain-text access log would only duplicate it.
    access_logger = logging.getLogger("uvicorn.access")
    access_logger.handlers.clear()
    access_logger.propagate = False
    access_logger.disabled = True
