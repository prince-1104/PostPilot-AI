"""LinkedIn publishing adapters (Phase 4A: fake only)."""

from app.publishing.factory import build_publisher
from app.publishing.outcomes import OutcomeKind, PublishExecutionContext, PublishOutcome

__all__ = [
    "OutcomeKind",
    "PublishExecutionContext",
    "PublishOutcome",
    "build_publisher",
]
