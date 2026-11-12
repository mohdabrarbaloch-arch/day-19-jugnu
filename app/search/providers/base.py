"""Provider interface.

A provider's only job is: given a question, return candidate URLs with titles
and snippets. Fetching and cleaning the pages is the fetcher's job, so providers
stay small and swappable.
"""

from __future__ import annotations

import abc

import httpx

from app.search.types import RawResult


class SearchProvider(abc.ABC):
    """Base class for every retrieval backend."""

    name: str = "base"
    #: Providers that need a key are skipped when it is absent.
    requires_key: bool = False

    def __init__(self, client: httpx.AsyncClient) -> None:
        self.client = client

    @property
    def available(self) -> bool:
        return True

    @abc.abstractmethod
    async def search(self, question: str, *, limit: int = 6) -> list[RawResult]:
        """Return up to `limit` candidate results. Raise on hard failure."""
        raise NotImplementedError

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<{type(self).__name__} name={self.name}>"
