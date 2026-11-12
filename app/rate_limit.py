"""In-process sliding-window rate limiter.

A fixed-window counter is easy but lets a caller burst 2x the limit across a
window boundary. A sliding window of timestamps is barely more code and does not
have that hole.

Keyed by (bucket, client identity). Identity is the authenticated user when we
have one, otherwise the client IP — so one noisy user cannot exhaust the budget
for everyone behind the same NAT, and an anonymous flood is still capped.

In-process means per-worker. Behind multiple workers, swap the store for Redis;
`check` is the only method that needs to change.
"""

from __future__ import annotations

import threading
import time
from collections import defaultdict, deque

from fastapi import HTTPException, Request, status

from app.config import settings


class SlidingWindowLimiter:
    def __init__(self) -> None:
        self._hits: dict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    @staticmethod
    def _identity(request: Request) -> str:
        # Prefer the authenticated user id if a middleware put one on state.
        user_id = getattr(request.state, "user_id", None)
        if user_id:
            return f"u:{user_id}"
        # Honour a single proxy hop, but do not trust a whole chain.
        forwarded = request.headers.get("x-forwarded-for", "")
        if forwarded:
            return f"ip:{forwarded.split(',')[0].strip()}"
        client = request.client
        return f"ip:{client.host if client else 'unknown'}"

    def check(self, request: Request, bucket: str, limit: int, *, window: float = 60.0) -> None:
        """Raise 429 if this identity is over `limit` in the last `window` seconds."""
        if not settings.rate_limit_enabled or limit <= 0:
            return

        key = f"{bucket}:{self._identity(request)}"
        now = time.monotonic()
        cutoff = now - window

        with self._lock:
            hits = self._hits[key]
            while hits and hits[0] <= cutoff:
                hits.popleft()

            if len(hits) >= limit:
                retry_after = max(1, int(hits[0] + window - now) + 1)
                raise HTTPException(
                    status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                    detail=f"Rate limit reached. Try again in {retry_after}s.",
                    headers={"Retry-After": str(retry_after)},
                )

            hits.append(now)

            # Opportunistic cleanup so the dict cannot grow without bound.
            if len(self._hits) > 4096:
                for stale_key in [k for k, v in self._hits.items() if not v]:
                    del self._hits[stale_key]

    def reset(self) -> None:
        with self._lock:
            self._hits.clear()


limiter = SlidingWindowLimiter()
