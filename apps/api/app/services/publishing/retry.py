"""Retry delay calculation for known-safe publishing failures."""

from __future__ import annotations

import random
from datetime import UTC, datetime, timedelta

from app.core.config import Settings


def compute_retry_at(
    *,
    settings: Settings,
    attempt_number: int,
    clock: datetime,
    retry_after_seconds: int | None = None,
) -> datetime:
    """Return the next attempt instant using exponential backoff with jitter.

    When the provider supplies a Retry-After, that lower bound is honored.
    """
    base = settings.publish_retry_initial_seconds * (
        settings.publish_retry_backoff_multiplier ** max(attempt_number - 1, 0)
    )
    capped = min(base, float(settings.publish_retry_max_delay_seconds))
    # Full jitter in [0.5, 1.0] of the capped delay.
    delay = capped * (0.5 + random.random() * 0.5)  # noqa: S311 — not crypto
    if retry_after_seconds is not None:
        delay = max(delay, float(retry_after_seconds))
    return clock.astimezone(UTC) + timedelta(seconds=delay)


def attempts_exhausted(*, settings: Settings, attempt_count: int) -> bool:
    return attempt_count >= settings.publish_retry_max_attempts
