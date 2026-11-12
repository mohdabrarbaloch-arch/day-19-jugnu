"""A tiny TTL + LRU cache.

Search is the expensive part of this app: several network round-trips per
question. Repeat questions are common (people retype, they share links, they hit
refresh), so caching the whole outcome for a few minutes removes most of the
load without ever serving something stale enough to matter.

Deliberately in-process. A multi-worker deployment should swap this for Redis —
the interface is small enough that it is a drop-in.
"""

from __future__ import annotations

import hashlib
import threading
import time
from collections import OrderedDict
from typing import Generic, TypeVar

T = TypeVar("T")


def make_key(*parts: str) -> str:
    joined = "\x1f".join(parts)
    return hashlib.sha256(joined.encode("utf-8")).hexdigest()[:32]


class TTLCache(Generic[T]):
    def __init__(self, *, ttl_seconds: int = 300, max_entries: int = 512) -> None:
        self.ttl = max(1, ttl_seconds)
        self.max_entries = max(1, max_entries)
        self._store: OrderedDict[str, tuple[float, T]] = OrderedDict()
        self._lock = threading.Lock()
        self.hits = 0
        self.misses = 0

    def get(self, key: str) -> T | None:
        now = time.monotonic()
        with self._lock:
            entry = self._store.get(key)
            if entry is None:
                self.misses += 1
                return None
            expires_at, value = entry
            if expires_at <= now:
                del self._store[key]
                self.misses += 1
                return None
            # Refresh LRU position.
            self._store.move_to_end(key)
            self.hits += 1
            return value

    def set(self, key: str, value: T) -> None:
        expires_at = time.monotonic() + self.ttl
        with self._lock:
            self._store[key] = (expires_at, value)
            self._store.move_to_end(key)
            while len(self._store) > self.max_entries:
                self._store.popitem(last=False)

    def clear(self) -> None:
        with self._lock:
            self._store.clear()

    def stats(self) -> dict[str, int]:
        with self._lock:
            return {
                "entries": len(self._store),
                "hits": self.hits,
                "misses": self.misses,
                "max_entries": self.max_entries,
                "ttl_seconds": self.ttl,
            }
