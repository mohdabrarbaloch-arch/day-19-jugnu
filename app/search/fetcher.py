"""Page fetcher and cleaner.

Turns a URL into readable prose. Three rules matter here:

1. **Bound everything.** A search result can point at a 400 MB PDF or a server
   that never closes the connection. We cap bytes, cap time, and only accept
   text/html.
2. **Never trust the network.** Any failure returns a Document with
   `fetched_ok=False` and the provider's snippet as the text, so the answer can
   still cite something real instead of dropping the source.
3. **Strip the chrome.** Nav, footers, cookie banners and sidebars are noise
   that pollutes passage selection. We remove them by tag and by class name
   before extracting text.
"""

from __future__ import annotations

import asyncio
import re

import httpx
from bs4 import BeautifulSoup

from app.config import settings
from app.search.text import normalise, truncate
from app.search.types import Document, RawResult

# Tags that never contain article prose.
_DROP_TAGS = (
    "script",
    "style",
    "noscript",
    "nav",
    "header",
    "footer",
    "aside",
    "form",
    "iframe",
    "svg",
    "button",
    "select",
    "input",
    "textarea",
    # Tables flatten into unreadable runs of cell text ("Type Aspect Charge
    # qubit RF-SQUID qubit ...") that score well on keywords and read as
    # nonsense. A table is data, not prose, so it is not a citable sentence.
    "table",
    "thead",
    "tbody",
    "tfoot",
    "tr",
    "td",
    "th",
    "caption",
)

# Class/id fragments that mark boilerplate on most CMSes.
# Word-bounded on purpose: a substring match would hit things like
# "vector-feature-language-in-header-enabled" on <html> and delete the page.
_BOILERPLATE = re.compile(
    r"(?:^|[\s_-])(?:"
    r"cookie|consent|banner|newsletter|subscribe|sidebar|related|share|social|"
    r"comments?|advert|advertisement|promo|breadcrumb|menu|navbar|popup|modal|"
    r"paywall|signup"
    r")(?:$|[\s_-])",
    re.IGNORECASE,
)

# Never remove these, whatever their class says.
_PROTECTED_TAGS = frozenset({"html", "body", "main", "article"})

# Sections that are structurally part of a page but never answer a question:
# reference lists, navboxes, infoboxes, tables of contents, edit links. On
# Wikipedia these hold thousands of characters of citation text that would
# otherwise outrank the actual prose.
_JUNK_SELECTORS = (
    ".reflist",
    ".references",
    ".mw-references-wrap",
    ".mw-editsection",
    ".navbox",
    ".infobox",
    ".vertical-navbox",
    ".toc",
    "#toc",
    ".mw-jump-link",
    ".catlinks",
    ".printfooter",
    ".mw-cite-backlink",
    "sup.reference",
    ".hatnote",
    ".metadata",
    ".ambox",
    ".sistersitebox",
    ".side-box",
    ".authority-control",
    ".shortdescription",
)

# Headings after which the rest of the page is apparatus, not content.
_TERMINAL_HEADINGS = (
    "references",
    "see also",
    "external links",
    "further reading",
    "bibliography",
    "notes",
    "citations",
    "sources",
)

# Where the real content usually lives, best first.
_CONTENT_SELECTORS = (
    "article",
    "main",
    "[role=main]",
    "#content",
    ".post-content",
    ".entry-content",
    ".article-body",
    ".markdown-body",
    "div.content",
)

_WS = re.compile(r"[ \t\u00a0]+")
_BLANK_LINES = re.compile(r"\n{3,}")

# Site chrome that survives tag stripping because it is plain text.
_TEXT_NOISE = re.compile(
    r"^(?:from wikipedia, the free encyclopedia|jump to (?:content|navigation|search)|"
    r"main page|contents|current events|random article|about wikipedia|"
    r"privacy policy|terms of use|cookie statement|mobile view)\s*$",
    re.IGNORECASE,
)


def clean_html(html: str) -> tuple[str, str]:
    """Return (title, body_text) from raw HTML."""
    soup = BeautifulSoup(html, "lxml")

    title = ""
    if soup.title and soup.title.string:
        title = normalise(soup.title.string)
    if not title:
        og = soup.find("meta", property="og:title")
        if og and og.get("content"):
            title = normalise(str(og["content"]))

    for tag in soup(_DROP_TAGS):
        tag.decompose()

    for selector in _JUNK_SELECTORS:
        for junk in soup.select(selector):
            junk.decompose()

    # Cut everything from the first terminal heading onwards. On an article
    # page that is where the reference list starts, and nothing after it is
    # prose worth quoting.
    for heading in soup.find_all(["h2", "h3"]):
        label = heading.get_text(" ", strip=True).lower().strip("[]")
        if label in _TERMINAL_HEADINGS:
            for sibling in list(heading.find_all_next()):
                sibling.decompose()
            heading.decompose()
            break

    for element in soup.find_all(True):
        # find_all(True) can hand back nodes whose `attrs` is None (doctype,
        # comments, malformed markup). Read attrs defensively rather than
        # trusting .get() to exist.
        if element.name in _PROTECTED_TAGS:
            continue
        attrs = getattr(element, "attrs", None) or {}
        classes = attrs.get("class") or []
        if isinstance(classes, str):
            classes = [classes]
        marker = " ".join([*classes, attrs.get("id") or ""]).strip()
        if marker and _BOILERPLATE.search(marker):
            element.decompose()

    root = None
    for selector in _CONTENT_SELECTORS:
        found = soup.select_one(selector)
        if found is not None and len(found.get_text(strip=True)) > 200:
            root = found
            break
    if root is None:
        root = soup.body or soup

    text = root.get_text("\n", strip=True)
    text = _WS.sub(" ", text)
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    lines = [line for line in lines if not _TEXT_NOISE.match(line)]
    text = "\n".join(lines)
    text = _BLANK_LINES.sub("\n\n", text)
    return title, text.strip()


def _looks_like_html(content_type: str, body: bytes) -> bool:
    if "html" in content_type or "xml" in content_type:
        return True
    if content_type and "text/plain" in content_type:
        return True
    head = body[:512].lstrip().lower()
    return head.startswith(b"<!doctype html") or head.startswith(b"<html")


class Fetcher:
    """Fetches and cleans pages with a concurrency cap."""

    def __init__(self, client: httpx.AsyncClient) -> None:
        self.client = client
        self._semaphore = asyncio.Semaphore(max(1, settings.fetch_concurrency))

    async def fetch(self, result: RawResult) -> Document:
        """Fetch one result. Never raises — failures degrade to snippet-only."""
        # A provider that already gave us a long body (Tavily) needs no fetch.
        if len(result.snippet) > 1200:
            return Document(
                title=result.title,
                url=result.url,
                domain=result.domain,
                text=result.snippet,
                snippet=truncate(result.snippet, 320),
                published_at=result.published_at,
                fetched_ok=True,
            )

        async with self._semaphore:
            try:
                return await self._fetch_one(result)
            except Exception:
                # A single malformed page must never take down a whole search.
                # Any failure degrades to the provider's snippet.
                return self._fallback(result)

    async def _fetch_one(self, result: RawResult) -> Document:
        async with self.client.stream(
            "GET",
            result.url,
            follow_redirects=True,
            headers={"Accept": "text/html,application/xhtml+xml,text/plain;q=0.9"},
        ) as resp:
            if resp.status_code >= 400:
                return self._fallback(result)

            content_type = resp.headers.get("content-type", "").lower()
            if content_type and not any(ok in content_type for ok in ("html", "xml", "text/plain")):
                return self._fallback(result)

            chunks: list[bytes] = []
            total = 0
            async for chunk in resp.aiter_bytes():
                chunks.append(chunk)
                total += len(chunk)
                if total >= settings.fetch_max_bytes:
                    break
            body = b"".join(chunks)
            final_url = str(resp.url)

        if not _looks_like_html(content_type, body):
            return self._fallback(result)

        html = body.decode("utf-8", errors="replace")
        title, text = clean_html(html)

        if len(text) < 200:
            return self._fallback(result)

        return Document(
            title=title or result.title,
            url=final_url,
            domain=result.domain,
            text=text,
            snippet=truncate(result.snippet or text, 320),
            published_at=result.published_at,
            fetched_ok=True,
        )

    @staticmethod
    def _fallback(result: RawResult) -> Document:
        """No page, but we still have the provider's snippet — cite that."""
        return Document(
            title=result.title,
            url=result.url,
            domain=result.domain,
            text=result.snippet,
            snippet=truncate(result.snippet, 320),
            published_at=result.published_at,
            fetched_ok=False,
        )

    async def fetch_many(self, results: list[RawResult]) -> list[Document]:
        if not results:
            return []
        return list(await asyncio.gather(*(self.fetch(r) for r in results)))
