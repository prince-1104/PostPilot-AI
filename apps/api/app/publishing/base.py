"""Publisher protocol — Phase 4A uses a fake implementation only."""

from __future__ import annotations

from typing import Protocol

from app.models import LinkedInConnection
from app.publishing.outcomes import PublishExecutionContext, PublishOutcome


class LinkedInPublisher(Protocol):
    """Publishes text posts through LinkedIn (or a simulation)."""

    def publish_text_post(
        self,
        *,
        connection: LinkedInConnection,
        content: str,
        execution_context: PublishExecutionContext,
    ) -> PublishOutcome:
        """Publish commentary text. Must never log or return access tokens."""
        ...
