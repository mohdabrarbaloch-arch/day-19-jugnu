"""Tests for provider parsing and the provider registry.

Parsing is tested against saved markup rather than the live network, so the
suite is deterministic and does not hammer DuckDuckGo.
"""

from __future__ import annotations

import httpx
import pytest

from app.search.providers import REGISTRY, build_provider
from app.search.providers.duckduckgo import DuckDuckGoProvider, _unwrap_redirect
from app.search.providers.wikipedia import WikipediaProvider
from app.search.types import RawResult

DDG_LITE_HTML = """
<html><body><table>
  <tr><td><a class="result-link"
    href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fexample.com%2Fone">First Result</a></td></tr>
  <tr><td class="result-snippet">A snippet about the first result.</td></tr>
  <tr><td><a class="result-link" href="https://example.org/two">Second Result</a></td></tr>
  <tr><td class="result-snippet">A snippet about the second result.</td></tr>
</table></body></html>
"""


class TestUnwrapRedirect:
    def test_unwraps_ddg_redirect(self):
        wrapped = "//duckduckgo.com/l/?uddg=https%3A%2F%2Fexample.com%2Fpage"
        assert _unwrap_redirect(wrapped) == "https://example.com/page"

    def test_leaves_plain_url_alone(self):
        assert _unwrap_redirect("https://example.com/x") == "https://example.com/x"

    def test_adds_scheme_to_protocol_relative(self):
        assert _unwrap_redirect("//example.com/x") == "https://example.com/x"

    def test_empty_string(self):
        assert _unwrap_redirect("") == ""


class TestDuckDuckGoParsing:
    def test_parses_lite_markup(self):
        results = DuckDuckGoProvider._parse_lite(DDG_LITE_HTML, 10)
        assert len(results) == 2
        assert results[0].title == "First Result"
        assert results[0].url == "https://example.com/one"
        assert "first result" in results[0].snippet

    def test_respects_limit(self):
        assert len(DuckDuckGoProvider._parse_lite(DDG_LITE_HTML, 1)) == 1

    def test_ignores_non_http_links(self):
        html = '<a class="result-link" href="javascript:void(0)">Bad</a>'
        assert DuckDuckGoProvider._parse_lite(html, 10) == []

    def test_empty_markup(self):
        assert DuckDuckGoProvider._parse_lite("<html></html>", 10) == []


class TestRawResult:
    def test_domain_strips_www(self):
        assert RawResult("t", "https://www.example.com/a").domain == "example.com"

    def test_domain_without_www(self):
        assert RawResult("t", "https://en.wikipedia.org/wiki/X").domain == "en.wikipedia.org"

    def test_domain_on_bad_url(self):
        assert RawResult("t", "not a url").domain == ""


class TestRegistry:
    def test_known_providers_registered(self):
        for name in ("wikipedia", "duckduckgo", "tavily", "searxng"):
            assert name in REGISTRY

    def test_unknown_provider_returns_none(self):
        client = httpx.AsyncClient()
        try:
            assert build_provider("nonexistent", client) is None
        finally:
            import asyncio

            asyncio.get_event_loop_policy().new_event_loop().run_until_complete(client.aclose())

    def test_wikipedia_always_available(self):
        client = httpx.AsyncClient()
        try:
            provider = build_provider("wikipedia", client)
            assert isinstance(provider, WikipediaProvider)
            assert provider.available is True
        finally:
            import asyncio

            asyncio.get_event_loop_policy().new_event_loop().run_until_complete(client.aclose())

    def test_keyed_provider_unavailable_without_key(self, monkeypatch):
        from app.search.providers import tavily

        monkeypatch.setattr(tavily.settings, "tavily_api_key", None)
        client = httpx.AsyncClient()
        try:
            assert build_provider("tavily", client) is None
        finally:
            import asyncio

            asyncio.get_event_loop_policy().new_event_loop().run_until_complete(client.aclose())


@pytest.mark.parametrize(
    "url,expected",
    [
        ("https://a.com", "a.com"),
        ("https://www.b.org/x", "b.org"),
        ("http://sub.c.net", "sub.c.net"),
    ],
)
def test_domain_extraction(url, expected):
    assert RawResult("t", url).domain == expected
