# app/rate_limit.py
"""Thread-safe in-memory sliding-window rate limiter (per process; not shared between instances)."""
from __future__ import annotations

import threading
import time
from collections import deque
from dataclasses import dataclass
from typing import Callable


@dataclass(frozen=True)
class RateLimitResult:
    allowed: bool
    limit: int
    remaining: int
    retry_after: int


class SlidingWindowRateLimiter:
    def __init__(self, window_seconds: float = 60.0, clock: Callable[[], float] = time.monotonic) -> None:
        self.window = window_seconds
        self._clock = clock
        self._hits: dict[str, deque[float]] = {}
        self._lock = threading.Lock()  # sync endpoints run in a thread pool

    def check(self, key: str, limit: int) -> RateLimitResult:
        with self._lock:
            now = self._clock()
            hits = self._hits.setdefault(key, deque())
            cutoff = now - self.window
            while hits and hits[0] <= cutoff:
                hits.popleft()
            if len(hits) >= limit:
                return RateLimitResult(False, limit, 0, max(1, int(hits[0] + self.window - now) + 1))
            hits.append(now)
            return RateLimitResult(True, limit, limit - len(hits), 0)

    def reset(self, key: str) -> None:
        with self._lock:
            self._hits.pop(key, None)

    def cleanup(self) -> int:
        with self._lock:
            cutoff = self._clock() - self.window
            stale = [k for k, d in self._hits.items() if not d or d[-1] <= cutoff]
            for k in stale:
                del self._hits[k]
            return len(stale)
