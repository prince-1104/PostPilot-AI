"""Simple per-user rate limiter for assistant message turns."""

from __future__ import annotations

import time
from collections import defaultdict, deque
from http import HTTPStatus
from threading import Lock
from uuid import UUID

from app.core.errors import AppError


class RateLimitedError(AppError):
    status_code = HTTPStatus.TOO_MANY_REQUESTS
    code = "rate_limited"


class AssistantRateLimiter:
    def __init__(self, *, limit_per_minute: int) -> None:
        self._limit = limit_per_minute
        self._events: dict[UUID, deque[float]] = defaultdict(deque)
        self._lock = Lock()

    def check(self, user_id: UUID) -> None:
        now = time.monotonic()
        window = 60.0
        with self._lock:
            q = self._events[user_id]
            while q and now - q[0] > window:
                q.popleft()
            if len(q) >= self._limit:
                raise RateLimitedError(
                    "Too many assistant messages. Please wait a minute and try again."
                )
            q.append(now)


_limiters: dict[int, AssistantRateLimiter] = {}
_limiters_lock = Lock()


def get_assistant_rate_limiter(limit_per_minute: int) -> AssistantRateLimiter:
    with _limiters_lock:
        limiter = _limiters.get(limit_per_minute)
        if limiter is None:
            limiter = AssistantRateLimiter(limit_per_minute=limit_per_minute)
            _limiters[limit_per_minute] = limiter
        return limiter
