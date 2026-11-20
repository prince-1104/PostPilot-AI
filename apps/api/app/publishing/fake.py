"""Deterministic fake LinkedIn publisher for Phase 4A.

Never contacts LinkedIn. Outcomes are controlled by constructor queue, default
scenario, or inline content markers such as ``[[fake:rate_limit]]``.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from uuid import uuid4

from app.models import LinkedInConnection
from app.publishing.outcomes import (
    OutcomeKind,
    PublishExecutionContext,
    PublishOutcome,
)

_MARKER_RE = re.compile(r"\[\[fake:([a-z_]+)\]\]", re.IGNORECASE)

_SCENARIO_BUILDERS: dict[str, Callable[[], PublishOutcome]] = {}


def _register(name: str):
    def decorator(fn: Callable[[], PublishOutcome]):
        _SCENARIO_BUILDERS[name] = fn
        return fn

    return decorator


@_register("success")
def _success() -> PublishOutcome:
    return PublishOutcome(
        kind=OutcomeKind.SUCCESS,
        submission_started=True,
        provider_post_urn=f"urn:li:share:fake-{uuid4().hex[:16]}",
        http_status=201,
        simulated=True,
    )


@_register("rate_limit")
def _rate_limit() -> PublishOutcome:
    return PublishOutcome(
        kind=OutcomeKind.RETRYABLE,
        submission_started=True,
        http_status=429,
        error_category="rate_limit",
        sanitized_error_code="linkedin_rate_limited",
        retry_after_seconds=30,
        simulated=True,
    )


@_register("permanent")
def _permanent() -> PublishOutcome:
    return PublishOutcome(
        kind=OutcomeKind.PERMANENT,
        submission_started=True,
        http_status=400,
        error_category="provider_rejection",
        sanitized_error_code="linkedin_rejected_content",
        simulated=True,
    )


@_register("expired")
def _expired() -> PublishOutcome:
    return PublishOutcome(
        kind=OutcomeKind.CONNECTION_EXPIRED,
        submission_started=False,
        http_status=401,
        error_category="auth",
        sanitized_error_code="linkedin_token_expired",
        simulated=True,
    )


@_register("pre_network")
def _pre_network() -> PublishOutcome:
    return PublishOutcome(
        kind=OutcomeKind.PRE_NETWORK_FAILURE,
        submission_started=False,
        error_category="local",
        sanitized_error_code="publisher_pre_network_failure",
        simulated=True,
    )


@_register("ambiguous")
def _ambiguous() -> PublishOutcome:
    return PublishOutcome(
        kind=OutcomeKind.AMBIGUOUS,
        submission_started=True,
        error_category="timeout",
        sanitized_error_code="publisher_ambiguous_timeout",
        simulated=True,
    )


@_register("interrupt")
def _interrupt() -> PublishOutcome:
    return PublishOutcome(
        kind=OutcomeKind.INTERRUPTED,
        submission_started=True,
        error_category="worker",
        sanitized_error_code="publisher_simulated_interrupt",
        simulated=True,
    )


class FakeLinkedInPublisher:
    """In-process publisher used for automated tests and local simulation."""

    def __init__(
        self,
        *,
        default_scenario: str = "success",
        outcome_queue: list[PublishOutcome] | None = None,
    ) -> None:
        if default_scenario not in _SCENARIO_BUILDERS:
            raise ValueError(f"Unknown fake scenario {default_scenario!r}")
        self._default_scenario = default_scenario
        self._queue = list(outcome_queue or [])
        self.calls: list[dict[str, str]] = []

    def publish_text_post(
        self,
        *,
        connection: LinkedInConnection,
        content: str,
        execution_context: PublishExecutionContext,
    ) -> PublishOutcome:
        # Record only non-sensitive identifiers for assertions.
        self.calls.append(
            {
                "connection_id": str(connection.id),
                "attempt_id": execution_context.attempt_id,
                "fencing_token": execution_context.fencing_token,
            }
        )
        if self._queue:
            return self._queue.pop(0)

        marker = _MARKER_RE.search(content)
        scenario = marker.group(1).lower() if marker else self._default_scenario
        builder = _SCENARIO_BUILDERS.get(scenario, _SCENARIO_BUILDERS[self._default_scenario])
        return builder()
