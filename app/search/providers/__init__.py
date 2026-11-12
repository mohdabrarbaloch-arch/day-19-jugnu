"""Provider registry.

Adding a backend means writing one class and adding one line to `REGISTRY`.
The chain in `app.search.engine` reads provider names from settings, so no other
file needs to change.
"""

from __future__ import annotations

import httpx

from app.search.providers.base import SearchProvider
from app.search.providers.duckduckgo import DuckDuckGoProvider, ProviderUnavailable
from app.search.providers.searxng import SearxNGProvider
from app.search.providers.tavily import TavilyProvider
from app.search.providers.wikipedia import WikipediaProvider

REGISTRY: dict[str, type[SearchProvider]] = {
    "wikipedia": WikipediaProvider,
    "duckduckgo": DuckDuckGoProvider,
    "tavily": TavilyProvider,
    "searxng": SearxNGProvider,
}


def build_provider(name: str, client: httpx.AsyncClient) -> SearchProvider | None:
    """Instantiate a provider by name, or None if unknown/unavailable."""
    cls = REGISTRY.get(name.strip().lower())
    if cls is None:
        return None
    provider = cls(client)
    return provider if provider.available else None


__all__ = [
    "REGISTRY",
    "DuckDuckGoProvider",
    "ProviderUnavailable",
    "SearchProvider",
    "SearxNGProvider",
    "TavilyProvider",
    "WikipediaProvider",
    "build_provider",
]
