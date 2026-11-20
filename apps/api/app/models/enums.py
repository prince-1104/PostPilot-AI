"""Shared database enumerations."""

from enum import StrEnum


class ConnectionStatus(StrEnum):
    """Lifecycle of a stored LinkedIn authorization."""

    CONNECTED = "connected"
    DISCONNECTED = "disconnected"
    REAUTH_REQUIRED = "reauth_required"


class PostStatus(StrEnum):
    """Lifecycle of a scheduled LinkedIn post.

    Application create/update/cancel only write ``scheduled`` and ``cancelled``.
    Workers write ``processing``, ``published``, ``failed``, and ``requires_review``.
    """

    SCHEDULED = "scheduled"
    PROCESSING = "processing"
    PUBLISHED = "published"
    FAILED = "failed"
    CANCELLED = "cancelled"
    REQUIRES_REVIEW = "requires_review"


class AttemptExecutionState(StrEnum):
    """Durable state of a single publish attempt."""

    CLAIMED = "claimed"
    # Submission to the provider may have begun; set before the network call.
    SUBMITTING = "submitting"
    SUCCEEDED = "succeeded"
    RETRYABLE_FAILURE = "retryable_failure"
    PERMANENT_FAILURE = "permanent_failure"
    AMBIGUOUS = "ambiguous"
    INTERRUPTED = "interrupted"
