"""Wikipedia provider.

The one backend that needs no key, no scraping and no rate-limit dance. It is
the default first link in the chain because it is always reachable and its
content is genuinely citable — every claim has a stable, human-readable URL.

Two calls per search: the search API for candidate titles, then the summary
endpoint for a clean extract. That gives us a real snippet without fetching and
parsing article HTML.
"""

from __future__ import annotations

import asyncio
import re

import httpx

from app.search.providers.base import SearchProvider
from app.search.types import RawResult

API = "https://en.wikipedia.org/w/api.php"
SUMMARY = "https://en.wikipedia.org/api/rest_v1/page/summary/{title}"

_TAG_RE = re.compile(r"<[^>]+>")

# Words that carry no search signal. Wikipedia's own search engine is a plain
# BM25 over article text, so "how does photosynthesis work" ranks *Photosystem*
# above *Photosynthesis* — the question words dilute the one term that matters.
# Stripping them before the query is the single biggest quality win here.
_STOPWORDS = frozenset(
    [
        "a",
        "an",
        "the",
        "is",
        "are",
        "was",
        "were",
        "be",
        "been",
        "being",
        "do",
        "does",
        "did",
        "doing",
        "done",
        "how",
        "what",
        "who",
        "whom",
        "whose",
        "when",
        "where",
        "why",
        "which",
        "that",
        "this",
        "these",
        "those",
        "of",
        "in",
        "on",
        "at",
        "to",
        "for",
        "from",
        "by",
        "with",
        "about",
        "into",
        "over",
        "under",
        "between",
        "and",
        "or",
        "but",
        "not",
        "no",
        "nor",
        "so",
        "than",
        "then",
        "there",
        "here",
        "it",
        "its",
        "it's",
        "i",
        "me",
        "my",
        "we",
        "our",
        "you",
        "your",
        "he",
        "she",
        "they",
        "them",
        "their",
        "can",
        "could",
        "should",
        "would",
        "will",
        "shall",
        "may",
        "might",
        "must",
        "work",
        "works",
        "working",
        "mean",
        "means",
        "meaning",
        "explain",
        "explaine",
        "tell",
        "give",
        "show",
        "describe",
        "define",
        "definition",
        "please",
    ]
)


def _keywords(question: str) -> str:
    """Reduce a natural-language question to its searchable terms."""
    words = re.findall(r"[A-Za-z0-9']+", question.lower())
    kept = [w for w in words if w not in _STOPWORDS and len(w) > 1]
    # If stripping everything left us with nothing, fall back to the original.
    return " ".join(kept) if kept else question.strip()


def _title_match(query: str, title: str) -> float:
    """How closely a result title matches the cleaned query, 0..1.

    An exact title match is almost always the canonical article, so it should
    outrank a more obscure page that merely mentions the term more often.
    """
    q = set(_keywords(query).split())
    t = set(re.findall(r"[a-z0-9']+", title.lower()))
    if not q or not t:
        return 0.0
    overlap = len(q & t) / len(q)
    # Reward a title that is *only* the subject ("Photosynthesis") over one
    # that buries it ("C4 carbon fixation").
    brevity = len(q & t) / max(len(t), 1)
    # A title that *starts* with the subject is the canonical article far more
    # often than not: "Photosynthesis" beats "Anoxygenic photosynthesis", and
    # "Ada Lovelace" beats "Ada Lovelace Day". Prefix match is the tie-breaker.
    prefix = 1.0 if title.lower().startswith(_keywords(query)) else 0.0
    return 0.45 * overlap + 0.30 * brevity + 0.25 * prefix


def _strip_html(text: str) -> str:
    return _TAG_RE.sub("", text or "").strip()


class WikipediaProvider(SearchProvider):
    name = "wikipedia"

    async def search(self, question: str, *, limit: int = 6) -> list[RawResult]:
        query = _keywords(question)
        params = {
            "action": "query",
            "list": "search",
            "srsearch": query,
            "format": "json",
            "srlimit": str(max(1, min(limit, 10))),
            "srprop": "snippet|timestamp",
        }
        resp = await self.client.get(API, params=params)
        resp.raise_for_status()
        payload = resp.json()

        hits = payload.get("query", {}).get("search", []) or []
        if not hits:
            return []

        titles = [h.get("title", "") for h in hits if h.get("title")]
        summaries = await asyncio.gather(
            *(self._summary(t) for t in titles), return_exceptions=True
        )

        results: list[RawResult] = []
        for idx, hit in enumerate(hits):
            title = hit.get("title", "")
            if not title:
                continue
            summary = summaries[idx] if idx < len(summaries) else None
            extract = ""
            if isinstance(summary, dict):
                extract = summary.get("extract", "") or ""
            snippet = extract or _strip_html(hit.get("snippet", ""))
            # Blend the API's own ordering with how well the title matches the
            # subject, so the canonical article wins over a passing mention.
            api_rank = (len(hits) - idx) / len(hits)
            score = 0.55 * api_rank + 0.45 * _title_match(question, title)
            results.append(
                RawResult(
                    title=title,
                    url=f"https://en.wikipedia.org/wiki/{title.replace(' ', '_')}",
                    snippet=snippet,
                    published_at=hit.get("timestamp"),
                    score=round(score, 4),
                )
            )
        return results

    async def _summary(self, title: str) -> dict:
        try:
            resp = await self.client.get(
                SUMMARY.format(title=httpx.URL(path=title).path.lstrip("/")),
                follow_redirects=True,
            )
            if resp.status_code != 200:
                return {}
            return resp.json()
        except (httpx.HTTPError, ValueError):
            return {}
