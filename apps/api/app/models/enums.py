"""Shared database enumerations."""

from enum import StrEnum


class ConnectionStatus(StrEnum):
    """Lifecycle of a stored LinkedIn authorization."""

    CONNECTED = "connected"
    DISCONNECTED = "disconnected"
    REAUTH_REQUIRED = "reauth_required"


class PostStatus(StrEnum):
    """Lifecycle of a scheduled LinkedIn post.

    Phase 3 application code only creates ``scheduled`` and ``cancelled``.
    ``processing``, ``published``, and ``failed`` are reserved for Phase 4 workers.
    """

    SCHEDULED = "scheduled"
    PROCESSING = "processing"
    PUBLISHED = "published"
    FAILED = "failed"
    CANCELLED = "cancelled"
