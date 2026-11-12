"""DuckDuckGo HTML provider.

DuckDuckGo's HTML endpoint is the classic no-key web search. It is also the
least reliable of the backends: it rate-limits aggressively and sometimes serves
a challenge page instead of results. So this provider is written to fail *loudly
and cleanly* — it raises `ProviderUnavailable` rather than returning an empty
list, which lets the chain move on to the next backend instead of silently
answering from nothing.

Parsing is done with BeautifulSoup against the `lite` markup, with a fallback to
the `html` endpoint's class names, because DDG has shipped both shapes.
"""

from __future__ import annotations

import urllib.parse

import httpx
from bs4 import BeautifulSoup

from app.search.providers.base import SearchProvider
from app.search.types import RawResult

LITE = "https://lite.duckduckgo.com/lite/"
HTML = "https://html.duckduckgo.com/html/"


class ProviderUnavailable(RuntimeError):
    """Raised when a provider cannot serve results right now."""


def _unwrap_redirect(href: str) -> str:
    """DDG wraps outbound links as /l/?uddg=<encoded>. Unwrap them."""
    if not href:
        return ""
    if href.startswith("//"):
        href = "https:" + href
    parsed = urllib.parse.urlparse(href)
    if "duckduckgo.com" in parsed.netloc and parsed.path.startswith("/l/"):
        qs = urllib.parse.parse_qs(parsed.query)
        target = qs.get("uddg", [""])[0]
        if target:
            return target
    return href


class DuckDuckGoProvider(SearchProvider):
    name = "duckduckgo"

    async def search(self, question: str, *, limit: int = 6) -> list[RawResult]:
        results = await self._try_lite(question, limit)
        if results:
            return results
        results = await self._try_html(question, limit)
        if results:
            return results
        raise ProviderUnavailable("duckduckgo returned no parseable results")

    async def _post(self, url: str, question: str) -> str:
        resp = await self.client.post(
            url,
            data={"q": question},
            headers={
                "Content-Type": "application/x-www-form-urlencoded",
                "Referer": "https://duckduckgo.com/",
            },
        )
        if resp.status_code >= 400:
            raise ProviderUnavailable(f"duckduckgo http {resp.status_code}")
        return resp.text

    async def _try_lite(self, question: str, limit: int) -> list[RawResult]:
        try:
            body = await self._post(LITE, question)
        except (httpx.HTTPError, ProviderUnavailable):
            return []
        return self._parse_lite(body, limit)

    @staticmethod
    def _parse_lite(body: str, limit: int) -> list[RawResult]:
        soup = BeautifulSoup(body, "lxml")
        out: list[RawResult] = []

        # lite markup: a table where each result is a link row + snippet row.
        for link in soup.select("a.result-link"):
            href = _unwrap_redirect(link.get("href", ""))
            title = link.get_text(" ", strip=True)
            if not href.startswith("http") or not title:
                continue
            snippet = ""
            row = link.find_parent("tr")
            if row is not None:
                nxt = row.find_next_sibling("tr")
                if nxt is not None:
                    cell = nxt.select_one("td.result-snippet")
                    if cell is not None:
                        snippet = cell.get_text(" ", strip=True)
            out.append(RawResult(title=title, url=href, snippet=snippet))
            if len(out) >= limit:
                break
        return out

    async def _try_html(self, question: str, limit: int) -> list[RawResult]:
        try:
            body = await self._post(HTML, question)
        except (httpx.HTTPError, ProviderUnavailable):
            return []
        return self._parse_html(body, limit)

    @staticmethod
    def _parse_html(body: str, limit: int) -> list[RawResult]:
        soup = BeautifulSoup(body, "lxml")
        out: list[RawResult] = []
        for block in soup.select("div.result"):
            link = block.select_one("a.result__a")
            if link is None:
                continue
            href = _unwrap_redirect(link.get("href", ""))
            title = link.get_text(" ", strip=True)
            if not href.startswith("http") or not title:
                continue
            snip_el = block.select_one(".result__snippet")
            snippet = snip_el.get_text(" ", strip=True) if snip_el else ""
            out.append(RawResult(title=title, url=href, snippet=snippet))
            if len(out) >= limit:
                break
        return out
