"""Database engine, session factory and declarative base.

SQLite is the zero-config default; point DATABASE_URL at Postgres and the same
code runs unchanged. The engine is created lazily so tests can swap the URL.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.config import settings


class Base(DeclarativeBase):
    pass


def _make_engine(url: str) -> Engine:
    kwargs: dict = {"echo": settings.sql_echo, "future": True}
    if url.startswith("sqlite"):
        # check_same_thread=False is required because FastAPI runs sync
        # dependencies in a threadpool.
        kwargs["connect_args"] = {"check_same_thread": False}
    else:
        kwargs["pool_pre_ping"] = True
        kwargs["pool_size"] = 5
        kwargs["max_overflow"] = 10
    return create_engine(url, **kwargs)


engine: Engine = _make_engine(settings.database_url)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)


@event.listens_for(Engine, "connect")
def _sqlite_pragmas(dbapi_connection, _connection_record) -> None:
    """WAL + foreign keys make SQLite behave like a real database."""
    if "sqlite3" not in type(dbapi_connection).__module__:
        return
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA synchronous=NORMAL")
    cursor.close()


def get_db() -> Iterator[Session]:
    """FastAPI dependency."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@contextmanager
def session_scope() -> Iterator[Session]:
    """For scripts and background work."""
    db = SessionLocal()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def init_db() -> None:
    """Create tables. Alembic takes over once the schema starts moving."""
    from app import models  # noqa: F401  (registers mappers)

    Base.metadata.create_all(bind=engine)
