"""Lightweight OpenTelemetry-compatible span helpers (optional dependency)."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager, suppress

import structlog

logger = structlog.get_logger(__name__)

try:
    from opentelemetry import trace as otel_trace

    _TRACER = otel_trace.get_tracer("postpilot.assistant")
    _OTEL_AVAILABLE = True
except Exception:  # pragma: no cover - optional
    _TRACER = None
    _OTEL_AVAILABLE = False


@contextmanager
def node_span(name: str, *, attributes: dict | None = None) -> Iterator[None]:
    """Create an OTEL span when the SDK is installed; otherwise no-op."""
    attrs = {k: v for k, v in (attributes or {}).items() if v is not None}
    if not _OTEL_AVAILABLE or _TRACER is None:
        yield
        return
    with _TRACER.start_as_current_span(name) as span:
        for key, value in attrs.items():
            with suppress(Exception):
                span.set_attribute(key, value)
        yield
