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


class ConcurrentLimitError(AppError):
    status_code = HTTPStatus.TOO_MANY_REQUESTS
    code = "concurrent_limit"


class AssistantConcurrencyLimiter:
    """Per-user in-flight request cap (process-local)."""

    def __init__(self, *, max_concurrent: int) -> None:
        self._max = max_concurrent
        self._inflight: dict[UUID, int] = defaultdict(int)
        self._lock = Lock()

    def acquire(self, user_id: UUID) -> None:
        with self._lock:
            if self._inflight[user_id] >= self._max:
                raise ConcurrentLimitError(
                    "Another assistant request is already in progress. Please wait."
                )
            self._inflight[user_id] += 1

    def release(self, user_id: UUID) -> None:
        with self._lock:
            current = self._inflight.get(user_id, 0)
            if current <= 1:
                self._inflight.pop(user_id, None)
            else:
                self._inflight[user_id] = current - 1


_concurrency: dict[int, AssistantConcurrencyLimiter] = {}
_concurrency_lock = Lock()


def get_assistant_concurrency_limiter(max_concurrent: int) -> AssistantConcurrencyLimiter:
    with _concurrency_lock:
        limiter = _concurrency.get(max_concurrent)
        if limiter is None:
            limiter = AssistantConcurrencyLimiter(max_concurrent=max_concurrent)
            _concurrency[max_concurrent] = limiter
        return limiter
