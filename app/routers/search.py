"""Search endpoint — the product.

One POST does the whole job: retrieve, fetch, rank, synthesise, persist. It
works signed-out (nothing is saved) and signed-in (the thread is stored so the
user can come back to it).
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime

from fastapi import APIRouter, HTTPException, Request, status

from app.config import settings
from app.models import Query, Source, Thread
from app.rate_limit import limiter
from app.schemas import QueryOut, SearchRequest, SearchResponse, SourceOut
from app.search import engine
from app.search.text import truncate
from app.security import DbSession, OptionalUser

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api", tags=["search"])


def _title_from(question: str) -> str:
    return truncate(question, 90) or "New search"


def _to_query_out(query: Query) -> QueryOut:
    return QueryOut(
        id=query.id,
        question=query.question,
        answer=query.answer,
        provider_used=query.provider_used,
        answer_provider=query.answer_provider,
        latency_ms=query.latency_ms,
        source_count=query.source_count,
        created_at=query.created_at,
        sources=[SourceOut.model_validate(s) for s in query.sources],
    )


@router.post(
    "/search",
    response_model=SearchResponse,
    summary="Ask a question, get a cited answer",
)
async def search(
    payload: SearchRequest,
    request: Request,
    db: DbSession,
    user: OptionalUser,
) -> SearchResponse:
    limiter.check(request, "search", settings.rate_limit_search_per_minute)

    # Resolve or create the thread. A thread id that is not ours is a 404, not a
    # 403 — we do not confirm that someone else's thread exists.
    thread: Thread | None = None
    if payload.thread_id:
        if user is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Sign in to continue a thread",
            )
        thread = db.get(Thread, payload.thread_id)
        if thread is None or thread.user_id != user.id:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Thread not found")

    result = await engine.search(payload.question)

    if not result.documents and result.provider == "none":
        # Retrieval genuinely failed. 503 is honest: the service, not the
        # question, is the problem.
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=(
                "No search backend could be reached. "
                f"Tried: {', '.join(result.failures) or 'none configured'}"
            ),
        )

    if user is None:
        # Signed-out: answer without persisting anything.
        return SearchResponse(
            thread_id="",
            thread_title=_title_from(payload.question),
            query=QueryOut(
                id="",
                question=payload.question,
                answer=result.answer.text,
                provider_used=result.provider,
                answer_provider=result.answer.provider,
                latency_ms=result.latency_ms,
                source_count=len(result.documents),
                created_at=datetime.now(UTC),
                sources=[
                    SourceOut(
                        rank=i,
                        title=d.title,
                        url=d.url,
                        domain=d.domain,
                        snippet=d.snippet,
                        published_at=d.published_at,
                        relevance=d.relevance,
                        fetched_ok=d.fetched_ok,
                    )
                    for i, d in enumerate(result.documents, start=1)
                ],
            ),
            follow_ups=result.answer.follow_ups,
        )

    if thread is None:
        thread = Thread(user_id=user.id, title=_title_from(payload.question))
        db.add(thread)
        db.flush()

    query = Query(
        thread_id=thread.id,
        question=payload.question,
        answer=result.answer.text,
        follow_ups="\n".join(result.answer.follow_ups),
        provider_used=result.provider,
        answer_provider=result.answer.provider,
        latency_ms=result.latency_ms,
        source_count=len(result.documents),
    )
    db.add(query)
    db.flush()

    for rank, doc in enumerate(result.documents, start=1):
        db.add(
            Source(
                query_id=query.id,
                rank=rank,
                title=truncate(doc.title, 400),
                url=doc.url,
                domain=doc.domain,
                snippet=doc.snippet,
                published_at=doc.published_at,
                relevance=doc.relevance,
                fetched_ok=doc.fetched_ok,
            )
        )

    thread.updated_at = query.created_at
    db.commit()
    db.refresh(query)

    return SearchResponse(
        thread_id=thread.id,
        thread_title=thread.title,
        query=_to_query_out(query),
        follow_ups=result.answer.follow_ups,
    )


@router.get("/search/suggest", summary="Autocomplete suggestions")
async def suggest(request: Request, q: str = "") -> dict[str, list[str]]:
    """Cheap prefix suggestions. No network, no cost."""
    limiter.check(request, "suggest", 60)
    q = q.strip().lower()
    if len(q) < 2:
        return {"suggestions": []}

    seeds = [
        "what is",
        "how does",
        "why do",
        "latest news about",
        "explain",
        "compare",
        "history of",
        "how to",
    ]
    return {"suggestions": [f"{seed} {q}" for seed in seeds][:6]}
