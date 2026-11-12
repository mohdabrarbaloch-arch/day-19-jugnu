"""Request/response models.

Every inbound field is bounded. A search box is the easiest place in an app to
get a 2 MB payload, so `question` is capped and stripped before it reaches the
retrieval layer.
"""

from __future__ import annotations

import re
from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

_CONTROL_CHARS = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


def _clean_text(value: str) -> str:
    """Strip control characters and collapse runaway whitespace."""
    value = _CONTROL_CHARS.sub("", value)
    return re.sub(r"[ \t]{2,}", " ", value).strip()


# --------------------------------------------------------------------------
# auth
# --------------------------------------------------------------------------
class RegisterRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=72)
    display_name: str = Field(min_length=1, max_length=80)

    @field_validator("display_name")
    @classmethod
    def _clean_name(cls, v: str) -> str:
        v = _clean_text(v)
        if not v:
            raise ValueError("display_name cannot be blank")
        return v

    @field_validator("password")
    @classmethod
    def _password_strength(cls, v: str) -> str:
        if v.strip() != v:
            raise ValueError("password cannot start or end with whitespace")
        if v.isdigit() or v.isalpha():
            raise ValueError("password must mix letters and numbers")
        return v


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=72)


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    email: str
    display_name: str
    is_admin: bool
    created_at: datetime


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int
    user: UserOut


# --------------------------------------------------------------------------
# search
# --------------------------------------------------------------------------
class SearchRequest(BaseModel):
    question: str = Field(min_length=2, max_length=500)
    thread_id: str | None = Field(default=None, max_length=32)
    # Optional: bias retrieval toward a region/language.
    focus: str | None = Field(default=None, max_length=40)

    @field_validator("question")
    @classmethod
    def _clean_question(cls, v: str) -> str:
        v = _clean_text(v)
        if len(v) < 2:
            raise ValueError("question is too short")
        return v


class SourceOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    rank: int
    title: str
    url: str
    domain: str
    snippet: str
    published_at: str | None = None
    relevance: float
    fetched_ok: bool


class QueryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    question: str
    answer: str
    provider_used: str
    answer_provider: str
    latency_ms: int
    source_count: int
    created_at: datetime
    sources: list[SourceOut] = Field(default_factory=list)

    @property
    def follow_ups(self) -> list[str]:
        return []


class SearchResponse(BaseModel):
    thread_id: str
    thread_title: str
    query: QueryOut
    follow_ups: list[str] = Field(default_factory=list)


class ThreadSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    title: str
    is_public: bool
    share_slug: str | None
    created_at: datetime
    updated_at: datetime
    query_count: int = 0


class ThreadDetail(ThreadSummary):
    queries: list[QueryOut] = Field(default_factory=list)


class ShareResponse(BaseModel):
    share_slug: str
    share_url: str


class HealthResponse(BaseModel):
    status: str
    version: str
    environment: str
    providers: list[str]
    answer_provider: str
    database: str


class ErrorResponse(BaseModel):
    detail: str
