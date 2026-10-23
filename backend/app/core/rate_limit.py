"""Lightweight in-memory sliding-window rate limiter.

NOTE: state lives in this process only. It is NOT shared between multiple
application instances (use Redis for that in a later phase).
"""
from __future__ import annotations

import time
from collections import deque
from dataclasses import dataclass
from typing import Callable


@dataclass(frozen=True)
class RateLimitResult:
    allowed: bool
    limit: int
    remaining: int
    retry_after: int  # seconds; 0 when allowed


class SlidingWindowRateLimiter:
    def __init__(self, window_seconds: float = 60.0, clock: Callable[[], float] = time.monotonic) -> None:
        self.window = window_seconds
        self._clock = clock
        self._hits: dict[str, deque[float]] = {}

    def check(self, key: str, limit: int) -> RateLimitResult:
        """Record a hit for `key` if under `limit`; the asyncio loop is single-threaded so no lock is needed."""
        now = self._clock()
        hits = self._hits.setdefault(key, deque())
        cutoff = now - self.window
        while hits and hits[0] <= cutoff:
            hits.popleft()
        if len(hits) >= limit:
            retry = max(1, int(hits[0] + self.window - now) + 1)
            return RateLimitResult(False, limit, 0, retry)
        hits.append(now)
        return RateLimitResult(True, limit, limit - len(hits), 0)

    def reset(self, key: str) -> None:
        self._hits.pop(key, None)

    def cleanup(self) -> int:
        """Drop idle keys; returns number removed."""
        cutoff = self._clock() - self.window
        stale = [k for k, d in self._hits.items() if not d or d[-1] <= cutoff]
        for k in stale:
            del self._hits[k]
        return len(stale)
