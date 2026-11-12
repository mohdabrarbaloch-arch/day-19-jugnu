"""ORM models.

Four tables carry the whole product:

    users      -> who is asking
    threads    -> a conversation (Perplexity calls these "threads")
    queries    -> one question inside a thread, with its answer
    sources    -> the citations behind one answer

A source row is the important one. It stores the exact snippet that was used to
build the answer, so a citation can always be traced back to text a human can
read — not just a URL that may have changed since.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


def _uuid() -> str:
    return uuid.uuid4().hex


def _now() -> datetime:
    return datetime.now(UTC)


class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    email: Mapped[str] = mapped_column(String(320), unique=True, index=True, nullable=False)
    display_name: Mapped[str] = mapped_column(String(80), nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    is_admin: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)

    threads: Mapped[list[Thread]] = relationship(
        back_populates="user", cascade="all, delete-orphan", passive_deletes=True
    )

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<User {self.email}>"


class Thread(Base):
    """A conversation. Every query belongs to exactly one thread."""

    __tablename__ = "threads"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False
    )
    title: Mapped[str] = mapped_column(String(200), nullable=False, default="New search")
    is_public: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    share_slug: Mapped[str | None] = mapped_column(String(24), unique=True, default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, onupdate=_now
    )

    user: Mapped[User] = relationship(back_populates="threads")
    queries: Mapped[list[Query]] = relationship(
        back_populates="thread",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="Query.created_at",
    )

    __table_args__ = (Index("ix_threads_user_updated", "user_id", "updated_at"),)


class Query(Base):
    """One question and the answer built for it."""

    __tablename__ = "queries"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    thread_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("threads.id", ondelete="CASCADE"), index=True, nullable=False
    )
    question: Mapped[str] = mapped_column(Text, nullable=False)
    answer: Mapped[str] = mapped_column(Text, nullable=False, default="")
    # Short follow-up questions the UI offers as chips.
    follow_ups: Mapped[str] = mapped_column(Text, nullable=False, default="")
    provider_used: Mapped[str] = mapped_column(String(40), nullable=False, default="")
    answer_provider: Mapped[str] = mapped_column(String(40), nullable=False, default="")
    latency_ms: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    source_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    thread: Mapped[Thread] = relationship(back_populates="queries")
    sources: Mapped[list[Source]] = relationship(
        back_populates="query",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="Source.rank",
    )

    __table_args__ = (Index("ix_queries_thread_created", "thread_id", "created_at"),)


class Source(Base):
    """A citation. `snippet` is the exact text the answer was built from."""

    __tablename__ = "sources"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    query_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("queries.id", ondelete="CASCADE"), index=True, nullable=False
    )
    rank: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    title: Mapped[str] = mapped_column(String(400), nullable=False, default="")
    url: Mapped[str] = mapped_column(Text, nullable=False)
    domain: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    snippet: Mapped[str] = mapped_column(Text, nullable=False, default="")
    published_at: Mapped[str | None] = mapped_column(String(40), default=None)
    # How much this source contributed to the answer, 0..1. Shown in the UI.
    relevance: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    fetched_ok: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    query: Mapped[Query] = relationship(back_populates="sources")

    __table_args__ = (UniqueConstraint("query_id", "rank", name="uq_source_query_rank"),)
