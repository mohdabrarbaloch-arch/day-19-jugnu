"""Tests for ranking and answer synthesis.

These encode the specific ranking bugs found while building: a weak source
outranking the canonical one, a caption winning passage selection, and a
follow-up suggestion that the corpus cannot answer.
"""

from __future__ import annotations

from app.search.answer import (
    _dedupe,
    _title_affinity,
    _valid_citations,
    make_follow_ups,
    rank_documents,
    synthesise_extractive,
)
from app.search.types import Document


def doc(title: str, text: str, *, url: str = "https://example.com/a", ok: bool = True) -> Document:
    return Document(
        title=title,
        url=url,
        domain="example.com",
        text=text,
        snippet=text[:200],
        fetched_ok=ok,
    )


class TestTitleAffinity:
    def test_exact_subject_scores_high(self):
        assert _title_affinity("what is quantum computing", "Quantum computing") > 0.9

    def test_narrower_subject_scores_lower(self):
        exact = _title_affinity("what is quantum computing", "Quantum computing")
        narrow = _title_affinity("what is quantum computing", "Quantum computing in India")
        assert narrow < exact

    def test_unrelated_title_scores_zero(self):
        assert _title_affinity("what is quantum computing", "Gardening") == 0.0

    def test_empty_title(self):
        assert _title_affinity("anything", "") == 0.0


class TestRankDocuments:
    def test_canonical_page_beats_narrower_page(self):
        # The real bug: "Quantum computing in India" outranked "Quantum computing".
        docs = [
            doc(
                "Quantum computing in India",
                "Quantum computing in India can be traced back to Satyendra Nath Bose. "
                "India is expected to invest around one billion dollars in quantum "
                "computing programs over the next five years.",
            ),
            doc(
                "Quantum computing",
                "Quantum computing is a type of computation that uses quantum "
                "mechanics. A qubit is the basic unit of information in quantum "
                "computing and serves a similar function to the bit.",
            ),
        ]
        ranked = rank_documents("what is quantum computing", docs)
        assert ranked[0].title == "Quantum computing"

    def test_relevance_is_bounded(self):
        docs = [doc("Test", "test " * 500)]
        ranked = rank_documents("test", docs)
        assert 0.0 <= ranked[0].relevance <= 1.0

    def test_empty_list(self):
        assert rank_documents("anything", []) == []

    def test_fetched_page_beats_snippet_only(self):
        docs = [
            doc("Topic", "topic content here", url="https://a.com", ok=False),
            doc("Topic", "topic content here", url="https://b.com", ok=True),
        ]
        ranked = rank_documents("topic content", docs)
        assert ranked[0].fetched_ok is True


class TestSynthesiseExtractive:
    def test_every_sentence_carries_a_citation(self):
        docs = [
            doc(
                "Vector database",
                "A vector database stores embeddings of data in vector space. "
                "It supports similarity search over those embeddings.",
            )
        ]
        answer = synthesise_extractive("what is a vector database", docs)
        assert "[1]" in answer
        # Every sentence in the output must end with a citation marker.
        for sentence in answer.split("] "):
            if sentence.strip():
                assert "[" in sentence

    def test_no_documents_says_so(self):
        answer = synthesise_extractive("anything", [])
        assert "could not find" in answer.lower()

    def test_uses_the_top_document_lede(self):
        docs = [
            doc(
                "Ada Lovelace",
                "Augusta Ada King was an English mathematician and writer. "
                "She is chiefly known for work on the analytical engine.",
            ),
            doc(
                "Ada Lovelace Award",
                "The Ada Lovelace Award is given in honor of Ada Lovelace by the "
                "Association for Women in Computing.",
            ),
        ]
        answer = synthesise_extractive("who was Ada Lovelace", docs)
        assert "mathematician" in answer

    def test_citation_numbers_are_within_range(self):
        docs = [doc(f"Doc {i}", f"Content about topic number {i} in detail.") for i in range(1, 4)]
        answer = synthesise_extractive("topic number", docs)
        for marker in answer.split("["):
            if "]" in marker:
                num = int(marker.split("]")[0])
                assert 1 <= num <= len(docs)


class TestDedupe:
    def test_removes_near_duplicates(self):
        pairs = [
            (1, "The quick brown fox jumps over the lazy dog in the park."),
            (2, "The quick brown fox jumps over the lazy dog in the park."),
        ]
        assert len(_dedupe(pairs)) == 1

    def test_keeps_distinct_sentences(self):
        pairs = [
            (1, "The quick brown fox jumps over the lazy dog."),
            (2, "Quantum computing uses qubits instead of classical bits."),
        ]
        assert len(_dedupe(pairs)) == 2


class TestValidCitations:
    def test_accepts_in_range_citations(self):
        assert _valid_citations("Something true [1] and more [2].", 3) is True

    def test_rejects_out_of_range_citation(self):
        assert _valid_citations("Something true [9].", 3) is False

    def test_rejects_answer_with_no_citation(self):
        assert _valid_citations("An answer with no citation at all here.", 3) is False

    def test_rejects_too_short(self):
        assert _valid_citations("Short [1]", 3) is False


class TestFollowUps:
    def test_suggestions_come_from_source_titles(self):
        # The subject page itself is skipped (it would just restate the
        # question), so a second, related page is what should surface.
        docs = [
            doc("Vector database", "content about vector databases here"),
            doc("Similarity search", "content about similarity search here"),
        ]
        follow_ups = make_follow_ups("what is a vector database", docs)
        assert any("Similarity search" in f for f in follow_ups)

    def test_never_suggests_the_question_itself(self):
        docs = [doc("Photosynthesis", "content about photosynthesis here")]
        follow_ups = make_follow_ups("what is photosynthesis", docs)
        assert all("what is photosynthesis" not in f.lower() for f in follow_ups)

    def test_falls_back_when_no_titles(self):
        follow_ups = make_follow_ups("anything", [])
        assert len(follow_ups) == 3

    def test_respects_limit(self):
        docs = [doc(f"Topic {i}", "content") for i in range(10)]
        assert len(make_follow_ups("question", docs, limit=2)) == 2
