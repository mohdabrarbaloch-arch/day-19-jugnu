"""Shared value objects for the retrieval layer."""

from __future__ import annotations

from dataclasses import dataclass, field
from urllib.parse import urlparse


@dataclass(slots=True)
class RawResult:
    """One hit from a search provider, before we fetch the page."""

    title: str
    url: str
    snippet: str = ""
    published_at: str | None = None
    # Provider's own ordering score, if it gives one.
    score: float = 0.0

    @property
    def domain(self) -> str:
        try:
            host = urlparse(self.url).netloc.lower()
        except ValueError:
            return ""
        return host[4:] if host.startswith("www.") else host


@dataclass(slots=True)
class Document:
    """A fetched, cleaned page — what the answer is actually built from."""

    title: str
    url: str
    domain: str
    text: str
    snippet: str = ""
    published_at: str | None = None
    relevance: float = 0.0
    fetched_ok: bool = False
    # Individual sentences pulled out as evidence, best first.
    passages: list[str] = field(default_factory=list)


@dataclass(slots=True)
class SearchOutcome:
    """What a provider chain returns: documents plus who served them."""

    documents: list[Document]
    provider: str
    # Providers that were tried and failed, for the health/debug surface.
    failures: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return bool(self.documents)
