"""Tests for the text layer — tokenising, sentence splitting, BM25, passages.

This is the ranking core, so it gets the most scrutiny. Every test here encodes
a real failure mode that showed up while building the engine.
"""

from __future__ import annotations

from app.search.text import (
    bm25_scores,
    coverage,
    normalise,
    select_passages,
    slugify,
    split_sentences,
    tokenize,
    truncate,
)


class TestTokenize:
    def test_drops_stopwords_and_short_tokens(self):
        assert tokenize("What is the best way to do it?") == ["best", "way"]

    def test_keeps_stopwords_when_asked(self):
        tokens = tokenize("the cat sat", keep_stopwords=True)
        assert tokens == ["the", "cat", "sat"]

    def test_lowercases_and_keeps_hyphens(self):
        assert "retrieval-augmented" in tokenize("Retrieval-Augmented generation")

    def test_empty_string(self):
        assert tokenize("") == []


class TestSplitSentences:
    def test_splits_on_terminators(self):
        text = (
            "Machine learning is a field of study. It builds models from data. "
            "Those models generalise to new examples."
        )
        assert len(split_sentences(text)) == 3

    def test_drops_short_fragments(self):
        assert split_sentences("Yes. No. Maybe so.") == []

    def test_drops_figure_captions(self):
        # This exact shape won passage selection on "what is photosynthesis"
        # and answered nothing.
        text = (
            "Schematic of photosynthesis in plants showing the light reactions. "
            "Photosynthesis is the process by which plants convert light into "
            "chemical energy."
        )
        sentences = split_sentences(text)
        assert len(sentences) == 1
        assert "convert light" in sentences[0]

    def test_drops_caption_phrases_mid_sentence(self):
        text = (
            "Composite image showing the global distribution of photosynthesis. "
            "The term photosynthesis usually refers to oxygenic photosynthesis."
        )
        sentences = split_sentences(text)
        assert len(sentences) == 1
        assert "oxygenic" in sentences[0]

    def test_drops_verbless_labels(self):
        assert split_sentences("Bloch sphere representation of a qubit") == []

    def test_keeps_long_verbless_text(self):
        # Long enough that it is probably prose with an unusual verb.
        long_label = "A " + "very " * 40 + "long descriptive phrase about things"
        assert len(split_sentences(long_label)) == 1


class TestBm25:
    def test_ranks_matching_document_higher(self):
        docs = [
            tokenize("cats and dogs living together"),
            tokenize("quantum computing uses qubits"),
        ]
        scores = bm25_scores(tokenize("quantum computing"), docs)
        assert scores[1] > scores[0]

    def test_rare_term_weighs_more_than_common(self):
        docs = [
            tokenize("the the the the the the rare"),
            tokenize("the the the the the the common"),
        ]
        scores = bm25_scores(tokenize("rare"), docs)
        assert scores[0] > scores[1]

    def test_empty_corpus(self):
        assert bm25_scores(tokenize("anything"), []) == []

    def test_empty_query(self):
        assert bm25_scores([], [tokenize("some text")]) == [0.0]


class TestCoverage:
    def test_full_coverage(self):
        assert coverage(tokenize("quantum computing"), "quantum computing is here") == 1.0

    def test_partial_coverage(self):
        assert coverage(tokenize("quantum computing"), "quantum physics") == 0.5

    def test_no_coverage(self):
        assert coverage(tokenize("quantum computing"), "gardening tips") == 0.0

    def test_empty_query(self):
        assert coverage([], "anything") == 0.0


class TestSelectPassages:
    def test_picks_the_relevant_sentence(self):
        sentences = [
            "The weather in Karachi is warm for most of the year.",
            "A vector database stores embeddings and supports similarity search.",
            "Many people enjoy cricket on the weekend.",
        ]
        chosen = select_passages("what is a vector database", sentences, limit=1)
        assert len(chosen) == 1
        assert "embeddings" in chosen[0]

    def test_returns_in_document_order(self):
        sentences = [
            "Alpha is the first letter and it starts the alphabet.",
            "Beta is the second letter and it follows alpha.",
            "Gamma is the third letter and it follows beta.",
        ]
        chosen = select_passages("letter alphabet", sentences, limit=3)
        # Whatever is chosen must come back in original order, not score order.
        indices = [sentences.index(s) for s in chosen]
        assert indices == sorted(indices)

    def test_empty_input(self):
        assert select_passages("anything", []) == []

    def test_no_query_tokens_returns_leading_sentences(self):
        sentences = ["First sentence here.", "Second sentence here."]
        assert select_passages("the a of", sentences, limit=1) == sentences[:1]


class TestHelpers:
    def test_normalise_collapses_whitespace(self):
        assert normalise("  a   b \n c  ") == "a b c"

    def test_truncate_on_word_boundary(self):
        result = truncate("the quick brown fox jumps", 15)
        assert result.endswith("…")
        assert not result[:-1].endswith(" ")

    def test_truncate_short_text_unchanged(self):
        assert truncate("short", 50) == "short"

    def test_slugify(self):
        assert slugify("What is RAG? A Guide!") == "what-is-rag-a-guide"

    def test_slugify_empty_falls_back(self):
        assert slugify("!!!") == "search"
