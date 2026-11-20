"""LinkedIn publishing adapters (fake + real)."""

from app.publishing.factory import build_publisher
from app.publishing.outcomes import OutcomeKind, PublishExecutionContext, PublishOutcome
from app.publishing.person_urn import linkedin_permalink_for_post_urn, person_urn_from_oidc_subject

__all__ = [
    "OutcomeKind",
    "PublishExecutionContext",
    "PublishOutcome",
    "build_publisher",
    "linkedin_permalink_for_post_urn",
    "person_urn_from_oidc_subject",
]
