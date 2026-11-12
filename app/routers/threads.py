"""Thread management: list, read, rename, share, delete.

Every read is scoped by `user_id` in the query itself rather than fetched-then-
checked. That way a missing thread and someone else's thread are the same code
path, and both return 404 — no way to probe for existence.
"""

from __future__ import annotations

import secrets

from fastapi import APIRouter, HTTPException, Response, status
from fastapi import Query as QueryParam
from sqlalchemy import func, select
from sqlalchemy.orm import selectinload

from app.models import Query, Thread
from app.schemas import (
    QueryOut,
    ShareResponse,
    SourceOut,
    ThreadDetail,
    ThreadSummary,
)
from app.security import CurrentUser, DbSession

router = APIRouter(prefix="/api/threads", tags=["threads"])


def _owned_thread(db, thread_id: str, user_id: str) -> Thread:
    thread = db.scalar(
        select(Thread)
        .where(Thread.id == thread_id, Thread.user_id == user_id)
        .options(selectinload(Thread.queries).selectinload(Query.sources))
    )
    if thread is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Thread not found")
    return thread


def _to_detail(thread: Thread) -> ThreadDetail:
    return ThreadDetail(
        id=thread.id,
        title=thread.title,
        is_public=thread.is_public,
        share_slug=thread.share_slug,
        created_at=thread.created_at,
        updated_at=thread.updated_at,
        query_count=len(thread.queries),
        queries=[
            QueryOut(
                id=q.id,
                question=q.question,
                answer=q.answer,
                provider_used=q.provider_used,
                answer_provider=q.answer_provider,
                latency_ms=q.latency_ms,
                source_count=q.source_count,
                created_at=q.created_at,
                sources=[SourceOut.model_validate(s) for s in q.sources],
            )
            for q in thread.queries
        ],
    )


@router.get("", response_model=list[ThreadSummary], summary="List my threads")
async def list_threads(
    user: CurrentUser,
    db: DbSession,
    limit: int = QueryParam(default=30, ge=1, le=100),
    offset: int = QueryParam(default=0, ge=0),
) -> list[ThreadSummary]:
    counts = (
        select(Query.thread_id, func.count(Query.id).label("n"))
        .group_by(Query.thread_id)
        .subquery()
    )
    rows = db.execute(
        select(Thread, func.coalesce(counts.c.n, 0))
        .outerjoin(counts, counts.c.thread_id == Thread.id)
        .where(Thread.user_id == user.id)
        .order_by(Thread.updated_at.desc())
        .limit(limit)
        .offset(offset)
    ).all()

    return [
        ThreadSummary(
            id=thread.id,
            title=thread.title,
            is_public=thread.is_public,
            share_slug=thread.share_slug,
            created_at=thread.created_at,
            updated_at=thread.updated_at,
            query_count=int(count),
        )
        for thread, count in rows
    ]


@router.get("/{thread_id}", response_model=ThreadDetail, summary="Read one thread")
async def get_thread(thread_id: str, user: CurrentUser, db: DbSession) -> ThreadDetail:
    return _to_detail(_owned_thread(db, thread_id, user.id))


@router.patch("/{thread_id}", response_model=ThreadSummary, summary="Rename a thread")
async def rename_thread(
    thread_id: str,
    user: CurrentUser,
    db: DbSession,
    title: str = QueryParam(min_length=1, max_length=200),
) -> ThreadSummary:
    thread = _owned_thread(db, thread_id, user.id)
    thread.title = title.strip()
    db.commit()
    db.refresh(thread)
    return ThreadSummary(
        id=thread.id,
        title=thread.title,
        is_public=thread.is_public,
        share_slug=thread.share_slug,
        created_at=thread.created_at,
        updated_at=thread.updated_at,
        query_count=len(thread.queries),
    )


@router.post("/{thread_id}/share", response_model=ShareResponse, summary="Make a thread public")
async def share_thread(thread_id: str, user: CurrentUser, db: DbSession) -> ShareResponse:
    thread = _owned_thread(db, thread_id, user.id)
    if not thread.share_slug:
        # 12 bytes of entropy: unguessable, still short enough to paste.
        thread.share_slug = secrets.token_urlsafe(9)
    thread.is_public = True
    db.commit()
    return ShareResponse(
        share_slug=thread.share_slug,
        share_url=f"/s/{thread.share_slug}",
    )


@router.delete(
    "/{thread_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
    summary="Delete a thread",
)
async def delete_thread(thread_id: str, user: CurrentUser, db: DbSession) -> Response:
    thread = _owned_thread(db, thread_id, user.id)
    db.delete(thread)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
