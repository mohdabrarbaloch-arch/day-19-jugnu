"""Tests for password hashing, JWT handling and the rate limiter."""

from __future__ import annotations

import pytest
from fastapi import HTTPException

from app.rate_limit import SlidingWindowLimiter
from app.security import (
    create_access_token,
    decode_token,
    hash_password,
    verify_password,
)


class TestPasswordHashing:
    def test_hash_is_not_the_plaintext(self):
        hashed = hash_password("hunter2secure")
        assert hashed != "hunter2secure"
        assert hashed.startswith("$2")

    def test_verify_accepts_correct_password(self):
        hashed = hash_password("hunter2secure")
        assert verify_password("hunter2secure", hashed) is True

    def test_verify_rejects_wrong_password(self):
        hashed = hash_password("hunter2secure")
        assert verify_password("wrongpassword", hashed) is False

    def test_same_password_hashes_differently(self):
        # bcrypt salts, so two hashes of the same input must not match.
        assert hash_password("hunter2secure") != hash_password("hunter2secure")

    def test_over_72_bytes_rejected(self):
        # bcrypt silently truncates past 72 bytes; we refuse instead.
        with pytest.raises(ValueError):
            hash_password("a" * 73)

    def test_verify_handles_garbage_hash(self):
        assert verify_password("anything", "not-a-hash") is False


class TestJwt:
    def test_round_trip(self):
        token = create_access_token("user-123")
        assert decode_token(token) == "user-123"

    def test_garbage_token_returns_none(self):
        assert decode_token("not.a.token") is None

    def test_tampered_token_returns_none(self):
        token = create_access_token("user-123")
        assert decode_token(token[:-4] + "aaaa") is None

    def test_expired_token_returns_none(self):
        token = create_access_token("user-123", expires_minutes=-1)
        assert decode_token(token) is None

    def test_token_signed_with_other_key_rejected(self, monkeypatch):
        from app import security

        token = create_access_token("user-123")
        monkeypatch.setattr(security.settings, "secret_key", "a-completely-different-key")
        assert decode_token(token) is None


class TestRateLimiter:
    class _FakeClient:
        host = "1.2.3.4"

    class _FakeRequest:
        def __init__(self):
            self.client = TestRateLimiter._FakeClient()
            self.headers = {}
            self.state = type("S", (), {"user_id": None})()

    @pytest.fixture(autouse=True)
    def _enable_limiting(self, monkeypatch):
        # conftest disables limiting globally so API tests stay fast; these
        # tests are specifically about the limiter, so turn it back on.
        from app import rate_limit

        monkeypatch.setattr(rate_limit.settings, "rate_limit_enabled", True)

    def test_allows_up_to_the_limit(self):
        limiter = SlidingWindowLimiter()
        req = self._FakeRequest()
        for _ in range(3):
            limiter.check(req, "test", 3)

    def test_blocks_over_the_limit(self):
        limiter = SlidingWindowLimiter()
        req = self._FakeRequest()
        for _ in range(3):
            limiter.check(req, "test", 3)
        with pytest.raises(HTTPException) as exc:
            limiter.check(req, "test", 3)
        assert exc.value.status_code == 429
        assert "Retry-After" in exc.value.headers

    def test_buckets_are_independent(self):
        limiter = SlidingWindowLimiter()
        req = self._FakeRequest()
        for _ in range(3):
            limiter.check(req, "search", 3)
        # A different bucket has its own budget.
        limiter.check(req, "auth", 3)

    def test_reset_clears_state(self):
        limiter = SlidingWindowLimiter()
        req = self._FakeRequest()
        for _ in range(3):
            limiter.check(req, "test", 3)
        limiter.reset()
        limiter.check(req, "test", 3)
