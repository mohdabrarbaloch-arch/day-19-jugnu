"""The search engine: question in, cited answer out.

Pipeline
--------
    question
       |
       v
    [cache] --hit--> return
       |
       v
    provider chain (wikipedia -> duckduckgo -> tavily -> searxng)
       |  first provider that returns results wins
       v
    fetcher (concurrent, bounded, degrades to snippet on failure)
       |
       v
    rank_documents (BM25 + coverage)
       |
       v
    synthesise (extractive, or LLM if configured)
       |
       v
    Answer + ranked Documents

The chain is the important design decision. A single provider is a single point
of failure, and every free search backend fails sometimes. Trying them in order
and taking the first that works means the app keeps answering when one of them
is rate-limited, blocked, or down.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field

import httpx

from app.config import settings
from app.search.answer import Answer, rank_documents, synthesise
from app.search.cache import TTLCache, make_key
from app.search.fetcher import Fetcher
from app.search.providers import ProviderUnavailable, build_provider
from app.search.types import Document, RawResult

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class SearchResult:
    answer: Answer
    documents: list[Document]
    provider: str
    latency_ms: int
    failures: list[str] = field(default_factory=list)
    cached: bool = False


class SearchEngine:
    def __init__(self) -> None:
        self._cache: TTLCache[SearchResult] = TTLCache(
            ttl_seconds=settings.cache_ttl_seconds,
            max_entries=settings.cache_max_entries,
        )

    # -- public ------------------------------------------------------------
    async def search(self, question: str, *, limit: int | None = None) -> SearchResult:
        started = time.perf_counter()
        max_sources = limit or settings.max_sources

        key = make_key(question.strip().lower(), str(max_sources), settings.answer_provider)
        cached = self._cache.get(key)
        if cached is not None:
            # Re-stamp latency so the UI shows this request's real cost.
            return SearchResult(
                answer=cached.answer,
                documents=cached.documents,
                provider=cached.provider,
                latency_ms=int((time.perf_counter() - started) * 1000),
                failures=cached.failures,
                cached=True,
            )

        async with httpx.AsyncClient(
            timeout=httpx.Timeout(settings.fetch_timeout_seconds),
            headers={
                "User-Agent": settings.user_agent,
                "Accept-Language": "en-US,en;q=0.9",
            },
            limits=httpx.Limits(max_connections=12, max_keepalive_connections=6),
        ) as client:
            raw, provider, failures = await self._retrieve(client, question, max_sources)

            if not raw:
                result = SearchResult(
                    answer=Answer(
                        text=(
                            "I could not reach any search backend for that question. "
                            "This is a retrieval failure, not an empty result — try "
                            "again in a moment."
                        ),
                        provider="none",
                        follow_ups=[],
                    ),
                    documents=[],
                    provider="none",
                    latency_ms=int((time.perf_counter() - started) * 1000),
                    failures=failures,
                )
                return result

            fetcher = Fetcher(client)
            documents = await fetcher.fetch_many(raw)
            documents = [d for d in documents if d.text.strip()]
            documents = rank_documents(question, documents)[:max_sources]

            answer = await synthesise(client, question, documents)

        result = SearchResult(
            answer=answer,
            documents=documents,
            provider=provider,
            latency_ms=int((time.perf_counter() - started) * 1000),
            failures=failures,
        )
        if documents:
            self._cache.set(key, result)
        return result

    # -- internals ---------------------------------------------------------
    async def _retrieve(
        self,
        client: httpx.AsyncClient,
        question: str,
        limit: int,
    ) -> tuple[list[RawResult], str, list[str]]:
        """Walk the provider chain until one returns results."""
        failures: list[str] = []
        chain = settings.provider_chain or ["wikipedia"]

        for name in chain:
            provider = build_provider(name, client)
            if provider is None:
                failures.append(f"{name}: unavailable (missing config)")
                continue
            try:
                results = await provider.search(question, limit=limit)
            except (ProviderUnavailable, httpx.HTTPError, ValueError, KeyError) as exc:
                logger.warning("provider %s failed: %s", name, exc)
                failures.append(f"{name}: {type(exc).__name__}")
                continue
            except TimeoutError:
                failures.append(f"{name}: timeout")
                continue

            if results:
                return results, name, failures
            failures.append(f"{name}: no results")

        return [], "none", failures

    def cache_stats(self) -> dict[str, int]:
        return self._cache.stats()

    def clear_cache(self) -> None:
        self._cache.clear()


engine = SearchEngine()
