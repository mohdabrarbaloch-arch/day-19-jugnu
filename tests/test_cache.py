"""Tests for the TTL/LRU cache and the rate limiter."""

from __future__ import annotations

import time

from app.search.cache import TTLCache, make_key


class TestTTLCache:
    def test_set_and_get(self):
        cache: TTLCache[str] = TTLCache(ttl_seconds=60)
        cache.set("k", "v")
        assert cache.get("k") == "v"

    def test_missing_key_returns_none(self):
        cache: TTLCache[str] = TTLCache(ttl_seconds=60)
        assert cache.get("nope") is None

    def test_expires(self):
        cache: TTLCache[str] = TTLCache(ttl_seconds=1)
        cache.set("k", "v")
        time.sleep(1.05)
        assert cache.get("k") is None

    def test_evicts_oldest_when_full(self):
        cache: TTLCache[int] = TTLCache(ttl_seconds=60, max_entries=2)
        cache.set("a", 1)
        cache.set("b", 2)
        cache.set("c", 3)
        assert cache.get("a") is None
        assert cache.get("c") == 3

    def test_get_refreshes_lru_position(self):
        cache: TTLCache[int] = TTLCache(ttl_seconds=60, max_entries=2)
        cache.set("a", 1)
        cache.set("b", 2)
        cache.get("a")  # "a" is now most-recently used
        cache.set("c", 3)  # should evict "b", not "a"
        assert cache.get("a") == 1
        assert cache.get("b") is None

    def test_stats_track_hits_and_misses(self):
        cache: TTLCache[str] = TTLCache(ttl_seconds=60)
        cache.set("k", "v")
        cache.get("k")
        cache.get("missing")
        stats = cache.stats()
        assert stats["hits"] == 1
        assert stats["misses"] == 1

    def test_clear(self):
        cache: TTLCache[str] = TTLCache(ttl_seconds=60)
        cache.set("k", "v")
        cache.clear()
        assert cache.get("k") is None


class TestMakeKey:
    def test_same_inputs_same_key(self):
        assert make_key("a", "b") == make_key("a", "b")

    def test_different_inputs_different_key(self):
        assert make_key("a", "b") != make_key("a", "c")

    def test_separator_prevents_collision(self):
        # Without a separator, ("ab","c") and ("a","bc") would collide.
        assert make_key("ab", "c") != make_key("a", "bc")

    def test_key_is_short(self):
        assert len(make_key("anything")) == 32
