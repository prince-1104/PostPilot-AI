"""Select the configured LinkedIn publisher implementation."""

from __future__ import annotations

from app.core.config import Settings
from app.core.security import TokenEncryptor
from app.publishing.base import LinkedInPublisher
from app.publishing.fake import FakeLinkedInPublisher
from app.publishing.real import RealLinkedInPublisher


def build_publisher(
    settings: Settings,
    *,
    encryptor: TokenEncryptor | None = None,
) -> LinkedInPublisher:
    provider = settings.publish_provider
    if provider == "fake":
        if settings.app_env == "production" and not settings.allow_fake_publisher_in_production:
            raise RuntimeError(
                "PUBLISH_PROVIDER=fake is refused when APP_ENV=production unless "
                "ALLOW_FAKE_PUBLISHER_IN_PRODUCTION=true for an isolated test environment."
            )
        return FakeLinkedInPublisher(default_scenario=settings.fake_publish_default_scenario)

    if provider == "linkedin":
        if not settings.enable_real_publishing:
            raise RuntimeError(
                "PUBLISH_PROVIDER=linkedin requires ENABLE_REAL_PUBLISHING=true."
            )
        if encryptor is None:
            encryptor = TokenEncryptor.from_settings_value(settings.token_encryption_key)
        return RealLinkedInPublisher(settings=settings, encryptor=encryptor)

    raise RuntimeError(f"Unknown PUBLISH_PROVIDER {provider!r}")
