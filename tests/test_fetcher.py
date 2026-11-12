"""Tests for the HTML cleaner.

The cleaner is where the two worst bugs lived: a substring class match that
deleted the entire document, and a crash on nodes whose `attrs` is None. Both
have a regression test here.
"""

from __future__ import annotations

from app.search.fetcher import _looks_like_html, clean_html

ARTICLE = """
<html class="client-nojs vector-feature-language-in-header-enabled">
<head><title>Retrieval-augmented generation - Wikipedia</title></head>
<body>
  <nav class="vector-menu">Home About Contact</nav>
  <div class="mw-content-text">
    <p>Retrieval-augmented generation is a technique that lets language models
    retrieve information from external sources before answering.</p>
    <p>It was introduced in a 2020 paper combining a parametric model with a
    non-parametric memory accessed at inference time.</p>
  </div>
  <div class="reflist">
    <p>Smith, John. "A study of retrieval." Journal of Things, 2021.</p>
  </div>
  <footer>Privacy policy</footer>
</body>
</html>
"""


class TestCleanHtml:
    def test_extracts_the_title(self):
        title, _ = clean_html(ARTICLE)
        assert "Retrieval-augmented generation" in title

    def test_keeps_the_article_prose(self):
        _, text = clean_html(ARTICLE)
        assert "technique that lets language models" in text
        assert "2020 paper" in text

    def test_does_not_delete_the_whole_document(self):
        # Regression: <html class="...in-header-enabled"> matched a substring
        # "header" rule and the entire page was decomposed, leaving 0 chars.
        _, text = clean_html(ARTICLE)
        assert len(text) > 100

    def test_strips_navigation(self):
        _, text = clean_html(ARTICLE)
        assert "Home About Contact" not in text

    def test_strips_footer(self):
        _, text = clean_html(ARTICLE)
        assert "Privacy policy" not in text

    def test_strips_reference_list(self):
        _, text = clean_html(ARTICLE)
        assert "Journal of Things" not in text

    def test_cuts_at_terminal_heading(self):
        html = """
        <html><body><article>
          <p>Photosynthesis is the process plants use to convert light energy
          into chemical energy stored in glucose molecules.</p>
          <h2>References</h2>
          <p>Smith, J. (2020). A book about plants. Publisher.</p>
        </article></body></html>
        """
        _, text = clean_html(html)
        assert "convert light energy" in text
        assert "A book about plants" not in text

    def test_handles_malformed_markup(self):
        # Regression: nodes with attrs=None raised AttributeError.
        html = "<html><body><p>Some real content that is long enough to keep here.</p>"
        _, text = clean_html(html)
        assert "real content" in text

    def test_handles_empty_document(self):
        title, text = clean_html("")
        assert title == ""
        assert text == ""

    def test_strips_site_chrome_lines(self):
        html = """
        <html><body><article>
          <p>From Wikipedia, the free encyclopedia</p>
          <p>Machine learning is a field of study in artificial intelligence
          concerned with algorithms that learn from data.</p>
        </article></body></html>
        """
        _, text = clean_html(html)
        assert "From Wikipedia, the free encyclopedia" not in text
        assert "field of study" in text


class TestLooksLikeHtml:
    def test_accepts_html_content_type(self):
        assert _looks_like_html("text/html; charset=utf-8", b"") is True

    def test_accepts_doctype_sniff(self):
        assert _looks_like_html("", b"<!DOCTYPE html><html>") is True

    def test_rejects_binary(self):
        assert _looks_like_html("application/pdf", b"%PDF-1.4") is False

    def test_rejects_image(self):
        assert _looks_like_html("image/png", b"\x89PNG\r\n") is False
