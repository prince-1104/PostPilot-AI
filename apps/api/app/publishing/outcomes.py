"""Typed outcomes returned by LinkedIn publishers."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class OutcomeKind(StrEnum):
    SUCCESS = "success"
    RETRYABLE = "retryable"
    PERMANENT = "permanent"
    CONNECTION_EXPIRED = "connection_expired"
    PRE_NETWORK_FAILURE = "pre_network_failure"
    AMBIGUOUS = "ambiguous"
    INTERRUPTED = "interrupted"


@dataclass(frozen=True, slots=True)
class PublishOutcome:
    kind: OutcomeKind
    # True once the publisher believes a provider request may have left this process.
    submission_started: bool
    provider_post_urn: str | None = None
    http_status: int | None = None
    error_category: str | None = None
    sanitized_error_code: str | None = None
    retry_after_seconds: int | None = None
    # When True the URN is from the deterministic fake provider, not LinkedIn.
    simulated: bool = False


@dataclass(frozen=True, slots=True)
class PublishExecutionContext:
    post_id: str
    attempt_id: str
    fencing_token: str
    attempt_number: int
    worker_id: str
    celery_task_id: str | None = None
