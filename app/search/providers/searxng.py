"""SearXNG provider — point it at your own instance for unlimited, private search.

SearXNG is a self-hosted metasearch engine with a clean JSON API. If you run one
(set SEARXNG_BASE_URL), this becomes the best backend in the chain: no key, no
quota, no scraping, and it aggregates Google/Bing/Brave for you.

Skipped automatically when SEARXNG_BASE_URL is unset.
"""

from __future__ import annotations

from app.config import settings
from app.search.providers.base import SearchProvider
from app.search.types import RawResult


class SearxNGProvider(SearchProvider):
    name = "searxng"
    requires_key = True

    @property
    def available(self) -> bool:
        return bool(settings.searxng_base_url)

    async def search(self, question: str, *, limit: int = 6) -> list[RawResult]:
        base = (settings.searxng_base_url or "").rstrip("/")
        if not base:
            return []

        resp = await self.client.get(
            f"{base}/search",
            params={
                "q": question,
                "format": "json",
                "safesearch": "1",
                "language": "en",
            },
        )
        resp.raise_for_status()
        data = resp.json()

        out: list[RawResult] = []
        for item in data.get("results", []) or []:
            url = item.get("url", "")
            if not url:
                continue
            out.append(
                RawResult(
                    title=item.get("title", "") or url,
                    url=url,
                    snippet=item.get("content", "") or "",
                    published_at=item.get("publishedDate"),
                    score=float(item.get("score", 0.0) or 0.0),
                )
            )
            if len(out) >= limit:
                break
        return out
