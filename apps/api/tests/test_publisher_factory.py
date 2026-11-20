"""Publisher factory: real mode never silently falls back to fake."""

from __future__ import annotations

import pytest

from app.publishing.factory import build_publisher
from app.publishing.fake import FakeLinkedInPublisher
from app.publishing.real import RealLinkedInPublisher


def test_default_settings_use_fake(settings_factory, token_encryptor) -> None:
    settings = settings_factory()
    assert settings.publish_provider == "fake"
    assert settings.enable_real_publishing is False
    publisher = build_publisher(settings, encryptor=token_encryptor)
    assert isinstance(publisher, FakeLinkedInPublisher)


def test_linkedin_provider_builds_real_publisher(settings_factory, token_encryptor) -> None:
    settings = settings_factory(
        publish_provider="linkedin",
        enable_real_publishing=True,
        live_publish_require_canary=True,
    )
    publisher = build_publisher(settings, encryptor=token_encryptor)
    assert isinstance(publisher, RealLinkedInPublisher)


def test_linkedin_without_enable_flag_refuses(settings_factory) -> None:
    with pytest.raises(Exception, match="ENABLE_REAL_PUBLISHING"):
        settings_factory(publish_provider="linkedin", enable_real_publishing=False)


def test_unknown_provider_refused(settings_factory, token_encryptor) -> None:
    class _Bogus:
        publish_provider = "bogus"
        app_env = "test"
        allow_fake_publisher_in_production = False
        enable_real_publishing = False
        fake_publish_default_scenario = "success"

    with pytest.raises(RuntimeError, match="Unknown PUBLISH_PROVIDER"):
        build_publisher(_Bogus(), encryptor=token_encryptor)  # type: ignore[arg-type]
