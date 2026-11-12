"""Tavily provider — the one you turn on when you want production-grade results.

Tavily returns already-extracted page content, which means the fetcher can skip
the network entirely for these hits. That is why `RawResult.snippet` is allowed
to be long: when a provider hands us real content we keep all of it.

Skipped automatically when TAVILY_API_KEY is unset.
"""

from __future__ import annotations

from app.config import settings
from app.search.providers.base import SearchProvider
from app.search.types import RawResult

ENDPOINT = "https://api.tavily.com/search"


class TavilyProvider(SearchProvider):
    name = "tavily"
    requires_key = True

    @property
    def available(self) -> bool:
        return bool(settings.tavily_api_key)

    async def search(self, question: str, *, limit: int = 6) -> list[RawResult]:
        if not settings.tavily_api_key:
            return []

        payload = {
            "api_key": settings.tavily_api_key,
            "query": question,
            "search_depth": "basic",
            "max_results": max(1, min(limit, 10)),
            "include_answer": False,
            "include_raw_content": True,
        }
        resp = await self.client.post(ENDPOINT, json=payload)
        resp.raise_for_status()
        data = resp.json()

        out: list[RawResult] = []
        for item in data.get("results", []) or []:
            url = item.get("url", "")
            if not url:
                continue
            # Prefer raw_content: it is the full page text, already extracted.
            body = item.get("raw_content") or item.get("content") or ""
            out.append(
                RawResult(
                    title=item.get("title", "") or url,
                    url=url,
                    snippet=body,
                    published_at=item.get("published_date"),
                    score=float(item.get("score", 0.0) or 0.0),
                )
            )
        return out
