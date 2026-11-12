"""API tests: auth, validation, ownership, rate limiting, health.

These hit the real app through TestClient. The search endpoint is exercised
against a stubbed engine so the suite stays fast and offline.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.search.answer import Answer
from app.search.engine import SearchResult
from app.search.types import Document


@pytest.fixture
def stub_engine(monkeypatch):
    """Replace the real engine with a deterministic offline one."""

    async def fake_search(question: str, *, limit: int | None = None) -> SearchResult:
        docs = [
            Document(
                title="Vector database",
                url="https://en.wikipedia.org/wiki/Vector_database",
                domain="en.wikipedia.org",
                text=(
                    "A vector database stores embeddings of data in vector space. "
                    "It supports similarity search over those embeddings."
                ),
                snippet="A vector database stores embeddings.",
                relevance=0.9,
                fetched_ok=True,
            )
        ]
        return SearchResult(
            answer=Answer(
                text="A vector database stores embeddings of data in vector space. [1]",
                provider="extractive",
                follow_ups=["How does similarity search work?"],
            ),
            documents=docs,
            provider="wikipedia",
            latency_ms=42,
        )

    # `app.search.__init__` re-exports the SearchEngine *class* under the name
    # `engine`, which shadows the submodule. importlib gets the real module.
    import importlib

    engine_module = importlib.import_module("app.search.engine")
    monkeypatch.setattr(engine_module.engine, "search", fake_search)
    return engine_module.engine


class TestHealth:
    def test_health_ok(self, client: TestClient):
        resp = client.get("/api/health")
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "ok"
        assert body["database"] == "ok"
        assert "providers" in body

    def test_security_headers_present(self, client: TestClient):
        resp = client.get("/api/health")
        assert resp.headers["X-Content-Type-Options"] == "nosniff"
        assert resp.headers["X-Frame-Options"] == "DENY"
        assert "Content-Security-Policy" in resp.headers


class TestAuth:
    def test_register_returns_token(self, client: TestClient, user_payload):
        resp = client.post("/api/auth/register", json=user_payload)
        assert resp.status_code == 201
        body = resp.json()
        assert body["token_type"] == "bearer"
        assert body["user"]["email"] == user_payload["email"]
        assert "password" not in body["user"]

    def test_duplicate_email_conflicts(self, client: TestClient, user_payload):
        client.post("/api/auth/register", json=user_payload)
        resp = client.post("/api/auth/register", json=user_payload)
        assert resp.status_code == 409

    def test_weak_password_rejected(self, client: TestClient):
        resp = client.post(
            "/api/auth/register",
            json={"email": "a@b.com", "password": "12345678", "display_name": "A"},
        )
        assert resp.status_code == 422

    def test_short_password_rejected(self, client: TestClient):
        resp = client.post(
            "/api/auth/register",
            json={"email": "a@b.com", "password": "ab1", "display_name": "A"},
        )
        assert resp.status_code == 422

    def test_invalid_email_rejected(self, client: TestClient):
        resp = client.post(
            "/api/auth/register",
            json={"email": "not-an-email", "password": "hunter2secure", "display_name": "A"},
        )
        assert resp.status_code == 422

    def test_login_succeeds(self, client: TestClient, user_payload):
        client.post("/api/auth/register", json=user_payload)
        resp = client.post(
            "/api/auth/login",
            json={"email": user_payload["email"], "password": user_payload["password"]},
        )
        assert resp.status_code == 200
        assert "access_token" in resp.json()

    def test_wrong_password_rejected(self, client: TestClient, user_payload):
        client.post("/api/auth/register", json=user_payload)
        resp = client.post(
            "/api/auth/login",
            json={"email": user_payload["email"], "password": "wrongpassword1"},
        )
        assert resp.status_code == 401

    def test_unknown_email_same_error_as_wrong_password(self, client: TestClient):
        # No account enumeration: identical status and message.
        resp = client.post(
            "/api/auth/login",
            json={"email": "nobody@example.com", "password": "hunter2secure"},
        )
        assert resp.status_code == 401
        assert resp.json()["detail"] == "Incorrect email or password"

    def test_me_requires_auth(self, client: TestClient):
        assert client.get("/api/auth/me").status_code == 401

    def test_me_returns_user(self, auth_client: TestClient):
        resp = auth_client.get("/api/auth/me")
        assert resp.status_code == 200
        assert resp.json()["display_name"] == "Test Tester"

    def test_garbage_token_rejected(self, client: TestClient):
        resp = client.get("/api/auth/me", headers={"Authorization": "Bearer not.a.token"})
        assert resp.status_code == 401


class TestSearch:
    def test_anonymous_search_works(self, client: TestClient, stub_engine):
        resp = client.post("/api/search", json={"question": "what is a vector database"})
        assert resp.status_code == 200
        body = resp.json()
        assert body["thread_id"] == ""  # nothing persisted for anonymous
        assert body["query"]["source_count"] == 1
        assert body["query"]["sources"][0]["domain"] == "en.wikipedia.org"
        assert body["follow_ups"]

    def test_authenticated_search_persists_thread(self, auth_client: TestClient, stub_engine):
        resp = auth_client.post("/api/search", json={"question": "what is a vector database"})
        assert resp.status_code == 200
        thread_id = resp.json()["thread_id"]
        assert thread_id

        detail = auth_client.get(f"/api/threads/{thread_id}")
        assert detail.status_code == 200
        assert len(detail.json()["queries"]) == 1

    def test_question_too_short_rejected(self, client: TestClient, stub_engine):
        resp = client.post("/api/search", json={"question": "a"})
        assert resp.status_code == 422

    def test_question_too_long_rejected(self, client: TestClient, stub_engine):
        resp = client.post("/api/search", json={"question": "x" * 600})
        assert resp.status_code == 422

    def test_control_characters_stripped(self, client: TestClient, stub_engine):
        resp = client.post("/api/search", json={"question": "what is\x00 a vector database"})
        assert resp.status_code == 200
        assert "\x00" not in resp.json()["query"]["question"]

    def test_anonymous_cannot_continue_thread(self, client: TestClient, stub_engine):
        resp = client.post(
            "/api/search",
            json={"question": "what is a vector database", "thread_id": "abc123"},
        )
        assert resp.status_code == 401


class TestThreads:
    def test_list_requires_auth(self, client: TestClient):
        assert client.get("/api/threads").status_code == 401

    def test_list_is_empty_for_new_user(self, auth_client: TestClient):
        resp = auth_client.get("/api/threads")
        assert resp.status_code == 200
        assert resp.json() == []

    def test_missing_thread_is_404(self, auth_client: TestClient):
        assert auth_client.get("/api/threads/doesnotexist").status_code == 404

    def test_other_users_thread_is_404_not_403(self, client: TestClient, stub_engine):
        # Owner A creates a thread.
        client.post(
            "/api/auth/register",
            json={"email": "a@example.com", "password": "hunter2secure", "display_name": "A"},
        )
        token_a = client.post(
            "/api/auth/login",
            json={"email": "a@example.com", "password": "hunter2secure"},
        ).json()["access_token"]
        created = client.post(
            "/api/search",
            json={"question": "what is a vector database"},
            headers={"Authorization": f"Bearer {token_a}"},
        ).json()
        thread_id = created["thread_id"]

        # Owner B tries to read it.
        client.post(
            "/api/auth/register",
            json={"email": "b@example.com", "password": "hunter2secure", "display_name": "B"},
        )
        token_b = client.post(
            "/api/auth/login",
            json={"email": "b@example.com", "password": "hunter2secure"},
        ).json()["access_token"]

        resp = client.get(
            f"/api/threads/{thread_id}", headers={"Authorization": f"Bearer {token_b}"}
        )
        # 404, not 403 — we do not confirm the thread exists.
        assert resp.status_code == 404

    def test_share_then_read_publicly(self, client: TestClient, stub_engine):
        client.post(
            "/api/auth/register",
            json={"email": "s@example.com", "password": "hunter2secure", "display_name": "S"},
        )
        token = client.post(
            "/api/auth/login",
            json={"email": "s@example.com", "password": "hunter2secure"},
        ).json()["access_token"]
        headers = {"Authorization": f"Bearer {token}"}

        thread_id = client.post(
            "/api/search",
            json={"question": "what is a vector database"},
            headers=headers,
        ).json()["thread_id"]

        share = client.post(f"/api/threads/{thread_id}/share", headers=headers)
        assert share.status_code == 200
        slug = share.json()["share_slug"]

        # Read it with no auth at all.
        public = client.get(f"/api/public/threads/{slug}")
        assert public.status_code == 200
        assert public.json()["is_public"] is True

    def test_unknown_share_slug_is_404(self, client: TestClient):
        assert client.get("/api/public/threads/nope").status_code == 404

    def test_delete_thread(self, auth_client: TestClient, stub_engine):
        thread_id = auth_client.post(
            "/api/search", json={"question": "what is a vector database"}
        ).json()["thread_id"]
        assert auth_client.delete(f"/api/threads/{thread_id}").status_code == 204
        assert auth_client.get(f"/api/threads/{thread_id}").status_code == 404

    def test_rename_thread(self, auth_client: TestClient, stub_engine):
        thread_id = auth_client.post(
            "/api/search", json={"question": "what is a vector database"}
        ).json()["thread_id"]
        resp = auth_client.patch(f"/api/threads/{thread_id}?title=My%20Research")
        assert resp.status_code == 200
        assert resp.json()["title"] == "My Research"


class TestSuggest:
    def test_short_query_returns_nothing(self, client: TestClient):
        assert client.get("/api/search/suggest?q=a").json()["suggestions"] == []

    def test_returns_suggestions(self, client: TestClient):
        resp = client.get("/api/search/suggest?q=quantum")
        assert resp.status_code == 200
        assert len(resp.json()["suggestions"]) > 0
