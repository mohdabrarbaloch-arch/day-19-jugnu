"""Public, unauthenticated surfaces: health and shared threads.

A shared thread is readable by anyone with the slug. It is read-only — there is
no endpoint that lets an anonymous visitor write to it.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.config import settings
from app.models import Query, Thread
from app.schemas import HealthResponse, QueryOut, SourceOut, ThreadDetail
from app.search import engine
from app.security import DbSession

router = APIRouter(tags=["public"])

VERSION = "1.0.0"


@router.get("/api/health", response_model=HealthResponse, summary="Health check")
async def health(db: DbSession) -> HealthResponse:
    database = "ok"
    try:
        db.execute(select(1))
    except Exception:
        database = "error"

    return HealthResponse(
        status="ok" if database == "ok" else "degraded",
        version=VERSION,
        environment=settings.environment,
        providers=settings.provider_chain,
        answer_provider=settings.answer_provider,
        database=database,
    )


@router.get("/api/stats", summary="Cache and provider stats")
async def stats() -> dict:
    return {
        "cache": engine.cache_stats(),
        "providers": settings.provider_chain,
        "answer_provider": settings.answer_provider,
        "version": VERSION,
    }


@router.get(
    "/api/public/threads/{slug}",
    response_model=ThreadDetail,
    summary="Read a shared thread",
)
async def public_thread(slug: str, db: DbSession) -> ThreadDetail:
    thread = db.scalar(
        select(Thread)
        .where(Thread.share_slug == slug, Thread.is_public.is_(True))
        .options(selectinload(Thread.queries).selectinload(Query.sources))
    )
    if thread is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Thread not found")

    return ThreadDetail(
        id=thread.id,
        title=thread.title,
        is_public=True,
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
