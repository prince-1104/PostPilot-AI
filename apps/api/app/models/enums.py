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


class AgentThreadStatus(StrEnum):
    """Lifecycle of an AI assistant conversation thread."""

    ACTIVE = "active"
    ARCHIVED = "archived"


class AgentMessageRole(StrEnum):
    USER = "user"
    ASSISTANT = "assistant"
    SYSTEM = "system"


class AgentDraftStatus(StrEnum):
    """Draft lifecycle. Scheduling always goes through PostService (Phase 5C)."""

    DRAFT = "draft"
    SUPERSEDED = "superseded"
    DISCARDED = "discarded"
    SCHEDULED = "scheduled"


class AgentDraftScheduleOpState(StrEnum):
    """Idempotent draft→PostService confirmation operation."""

    PENDING = "pending"
    CONFIRMED = "confirmed"
    FAILED = "failed"


class AssistantResponseState(StrEnum):
    """Machine-readable assistant turn outcomes for the UI."""

    NEEDS_INFORMATION = "needs_information"
    GENERATING = "generating"
    DRAFT_READY = "draft_ready"
    UNAVAILABLE = "unavailable"
    ERROR = "error"
