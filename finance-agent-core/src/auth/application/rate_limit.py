from __future__ import annotations

import asyncio
import time
from collections import defaultdict, deque

from src.auth.application.errors import RateLimitExceeded


class InMemoryRateLimiter:
    """Small bounded fallback until the shared Redis limiter is formalized."""

    def __init__(self) -> None:
        self._events: dict[str, deque[float]] = defaultdict(deque)
        self._lock = asyncio.Lock()

    async def check(self, *, key: str, limit: int, window_seconds: int) -> None:
        now = time.monotonic()
        cutoff = now - window_seconds
        async with self._lock:
            events = self._events[key]
            while events and events[0] <= cutoff:
                events.popleft()
            if len(events) >= limit:
                raise RateLimitExceeded("too many attempts; try again later")
            events.append(now)


rate_limiter = InMemoryRateLimiter()
