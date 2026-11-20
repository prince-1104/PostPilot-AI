"""Select the configured LinkedIn publisher implementation."""

from __future__ import annotations

from app.core.config import Settings
from app.publishing.base import LinkedInPublisher
from app.publishing.fake import FakeLinkedInPublisher


def build_publisher(settings: Settings) -> LinkedInPublisher:
    provider = settings.publish_provider
    if provider == "fake":
        if settings.app_env == "production" and not settings.allow_fake_publisher_in_production:
            raise RuntimeError(
                "PUBLISH_PROVIDER=fake is refused when APP_ENV=production unless "
                "ALLOW_FAKE_PUBLISHER_IN_PRODUCTION=true for an isolated test environment."
            )
        return FakeLinkedInPublisher(default_scenario=settings.fake_publish_default_scenario)

    if provider == "linkedin":
        raise RuntimeError(
            "Real LinkedIn publishing is Phase 4B and is not enabled in this build. "
            "Set PUBLISH_PROVIDER=fake for Phase 4A."
        )

    raise RuntimeError(f"Unknown PUBLISH_PROVIDER {provider!r}")
