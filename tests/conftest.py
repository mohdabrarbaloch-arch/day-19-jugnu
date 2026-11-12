"""Shared test fixtures.

Every test runs against a throwaway SQLite file and a fresh app instance, so
tests never touch a real database and never depend on each other's state.
"""

from __future__ import annotations

import os
import tempfile
from collections.abc import Iterator
from pathlib import Path

import pytest

# Must be set before app.config is imported anywhere.
_TMP_DB = Path(tempfile.mkdtemp(prefix="jugnu-test-")) / "test.db"
os.environ["DATABASE_URL"] = f"sqlite:///{_TMP_DB}"
os.environ["ENVIRONMENT"] = "test"
os.environ["SECRET_KEY"] = "test-secret-key-not-for-production"
os.environ["RATE_LIMIT_ENABLED"] = "false"
os.environ["BCRYPT_ROUNDS"] = "4"  # keep hashing fast in tests
os.environ["SEARCH_PROVIDERS"] = "wikipedia"
os.environ["ANSWER_PROVIDER"] = "extractive"

from fastapi.testclient import TestClient  # noqa: E402

from app.db import Base, engine  # noqa: E402
from app.main import app  # noqa: E402


@pytest.fixture(scope="session", autouse=True)
def _schema() -> Iterator[None]:
    Base.metadata.create_all(bind=engine)
    yield
    Base.metadata.drop_all(bind=engine)


@pytest.fixture(autouse=True)
def _clean_tables() -> Iterator[None]:
    """Wipe every table before each test.

    The schema is session-scoped for speed, but the data must not leak between
    tests — otherwise a second register with the same email returns 409 and
    every downstream test fails for the wrong reason.
    """
    with engine.begin() as conn:
        for table in reversed(Base.metadata.sorted_tables):
            conn.execute(table.delete())
    yield


@pytest.fixture
def client() -> Iterator[TestClient]:
    with TestClient(app) as c:
        yield c


@pytest.fixture
def user_payload() -> dict[str, str]:
    return {
        "email": "tester@example.com",
        "password": "hunter2secure",
        "display_name": "Test Tester",
    }


@pytest.fixture
def auth_client(client: TestClient, user_payload: dict[str, str]) -> TestClient:
    """A client with a registered, signed-in user."""
    resp = client.post("/api/auth/register", json=user_payload)
    assert resp.status_code == 201, resp.text
    token = resp.json()["access_token"]
    client.headers.update({"Authorization": f"Bearer {token}"})
    return client
