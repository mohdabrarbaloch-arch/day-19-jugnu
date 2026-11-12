"""Answer synthesis.

Two modes, one interface:

**extractive** (default) — no API key, no cost, no hallucination. It ranks the
sentences across all fetched documents, picks the ones that best cover the
question, and stitches them into a short answer with an inline citation marker
after every sentence. Every word in the answer is a quote from a real page, so
the citation is always true by construction.

**openai / anthropic** — the same retrieved passages are handed to an LLM with
strict instructions to answer only from them and cite with [n]. If the model
returns something unusable we fall back to extractive rather than shipping a
broken answer.

The extractive path is the interesting one: it is what makes this app work with
zero credentials, and it is honest about its limits — it quotes, it does not
reason.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

import httpx

from app.config import settings
from app.search.text import (
    bm25_scores,
    coverage,
    normalise,
    select_passages,
    split_sentences,
    tokenize,
    truncate,
)
from app.search.types import Document

_CITATION_RE = re.compile(r"\[(\d{1,2})\]")


@dataclass(slots=True)
class Answer:
    text: str
    provider: str
    follow_ups: list[str]


# --------------------------------------------------------------------------
# ranking
# --------------------------------------------------------------------------
def _title_affinity(question: str, title: str) -> float:
    """How closely a page's title matches the question, 0..1.

    Wikipedia's search happily returns "Quantum computing in India" for "what is
    quantum computing", and that page is *about* the topic without *defining*
    it. The canonical article is the one whose title is the subject itself, so
    we reward a title that is fully covered by the question's terms and penalise
    one that adds a lot of extra words.
    """
    q_tokens = set(tokenize(question))
    # Strip the site suffix ("Photosynthesis - Wikipedia") before comparing:
    # the site name is never part of the subject and would otherwise count as
    # an "extra word" on every single result, flattening the signal.
    clean_title = re.split(r"\s+[-|–—]\s+", title)[0]
    t_tokens = tokenize(clean_title)
    if not t_tokens or not q_tokens:
        return 0.0

    covered = len(set(t_tokens) & q_tokens) / len(set(t_tokens))
    # Extra words in the title mean a narrower subject than the question asked.
    extra = max(0, len(set(t_tokens) - q_tokens))
    penalty = 1.0 / (1.0 + 0.6 * extra)
    return covered * penalty


def rank_documents(question: str, documents: list[Document]) -> list[Document]:
    """Order documents by how well they answer the question.

    Blends BM25 (term rarity + frequency) with query coverage (did it address
    every part of the question), a title-affinity term (is this the canonical
    page for the subject), and a small bonus for pages we actually fetched.
    """
    if not documents:
        return []

    q_tokens = tokenize(question)
    if not q_tokens:
        return documents

    corpus = [tokenize(d.text) for d in documents]
    bm25 = bm25_scores(q_tokens, corpus)
    top = max(bm25) or 1.0

    for doc, score in zip(documents, bm25, strict=True):
        cov = coverage(q_tokens, doc.text)
        norm = score / top if top else 0.0
        affinity = _title_affinity(question, doc.title)
        bonus = 0.08 if doc.fetched_ok else 0.0
        # Title affinity carries real weight: BM25 over a long article rewards
        # any page that repeats the term a lot, which is how "Anoxygenic
        # photosynthesis" outranks "Photosynthesis". The title is the strongest
        # single signal we have about what a page is *about*.
        doc.relevance = round(min(1.0, 0.34 * norm + 0.24 * cov + 0.34 * affinity + bonus), 4)

    return sorted(documents, key=lambda d: d.relevance, reverse=True)


# --------------------------------------------------------------------------
# extractive synthesis
# --------------------------------------------------------------------------
def _best_sentences(
    question: str, documents: list[Document], per_doc: int = 2
) -> list[tuple[int, str]]:
    """Pick the strongest sentences, tagged with their 1-based source number.

    Document relevance is a *multiplier*, not an addend. That matters: without
    it, a sentence from a weak source that happens to repeat the question's
    words beats the actual answer sitting in the top document. With it, the
    best page dominates and the others only contribute when they say something
    the top page does not.
    """
    picked: list[tuple[float, int, str]] = []
    q_tokens = set(tokenize(question))

    for idx, doc in enumerate(documents, start=1):
        sentences = split_sentences(doc.text)
        if not sentences:
            continue
        chosen = select_passages(question, sentences, limit=per_doc)

        # The opening sentences of the best page are the definition of the
        # subject. For "who/what is X" questions that is almost always the
        # answer, and BM25 alone misses it because a lede rarely repeats the
        # question's words. Always consider the first two sentences of the top
        # document, and give them a lead bonus.
        if idx == 1:
            for lead in sentences[:2]:
                if lead not in chosen:
                    chosen.append(lead)

        for sentence in chosen:
            s_tokens = set(tokenize(sentence))
            if not s_tokens:
                continue
            overlap = len(q_tokens & s_tokens) / (len(q_tokens) or 1)
            # Prefer earlier sentences: the lede usually answers the question.
            position = 1.0 - (sentences.index(sentence) / max(len(sentences), 1)) * 0.3
            # Relevance multiplies, so a weak source cannot outrank a strong one
            # just by echoing the question's wording.
            score = overlap * position * (0.15 + doc.relevance) ** 2
            # Lead bonus: the first sentence of the top page is the definition.
            if idx == 1 and sentences.index(sentence) < 2:
                score *= 2.2
            picked.append((score, idx, sentence))

    picked.sort(key=lambda t: t[0], reverse=True)
    return [(idx, sentence) for _, idx, sentence in picked]


def _dedupe(sentences: list[tuple[int, str]]) -> list[tuple[int, str]]:
    """Drop near-duplicate sentences (same opening 60 chars, case-insensitive)."""
    seen: set[str] = set()
    out: list[tuple[int, str]] = []
    for idx, sentence in sentences:
        key = re.sub(r"\W+", "", sentence.lower())[:60]
        if key in seen:
            continue
        seen.add(key)
        out.append((idx, sentence))
    return out


def _tidy(text: str) -> str:
    """Remove the space that sentence-joining leaves before punctuation.

    Sentences are joined with " " so a citation marker can sit between them,
    which produces "vector space . [1]". This puts the punctuation back where
    it belongs.
    """
    text = re.sub(r"\s+([,.;:!?])", r"\1", text)
    text = re.sub(r"\(\s+", "(", text)
    text = re.sub(r"\s+\)", ")", text)
    return text.strip()


def synthesise_extractive(
    question: str, documents: list[Document], *, max_sentences: int = 4
) -> str:
    """Build a cited answer purely from retrieved text."""
    if not documents:
        return (
            "I could not find any sources for that question. Try rephrasing it, "
            "or ask something more specific."
        )

    candidates = _dedupe(_best_sentences(question, documents))
    if not candidates:
        # Nothing matched the question terms — say so instead of quoting noise.
        lead = truncate(documents[0].text, 300)
        return f"{lead} [1]"

    chosen = candidates[:max_sentences]
    # Present in source order so the answer reads as a coherent paragraph.
    chosen.sort(key=lambda pair: pair[0])

    parts: list[str] = []
    for idx, sentence in chosen:
        sentence = normalise(sentence)
        if not sentence.endswith((".", "!", "?")):
            sentence += "."
        parts.append(f"{sentence} [{idx}]")

    return _tidy(" ".join(parts))


# --------------------------------------------------------------------------
# LLM synthesis
# --------------------------------------------------------------------------
SYSTEM_PROMPT = (
    "You are a search assistant. Answer the user's question using ONLY the "
    "numbered sources provided. After every factual sentence, put the source "
    "number in square brackets, like [1] or [2][3]. If the sources do not "
    "contain the answer, say so plainly instead of guessing. Be concise: three "
    "to five sentences. Do not add a preamble, do not repeat the question, and "
    "never invent a citation number that is not in the list."
)


def build_context(documents: list[Document], *, per_doc_chars: int = 1800) -> str:
    blocks: list[str] = []
    for idx, doc in enumerate(documents, start=1):
        body = truncate(doc.text, per_doc_chars)
        blocks.append(f"[{idx}] {doc.title}\nURL: {doc.url}\n{body}")
    return "\n\n".join(blocks)


def build_user_prompt(question: str, documents: list[Document]) -> str:
    return f"Question: {question}\n\nSources:\n{build_context(documents)}"


async def _call_openai(client: httpx.AsyncClient, question: str, documents: list[Document]) -> str:
    resp = await client.post(
        "https://api.openai.com/v1/chat/completions",
        headers={"Authorization": f"Bearer {settings.openai_api_key}"},
        json={
            "model": settings.openai_model,
            "temperature": 0.2,
            "max_tokens": 500,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": build_user_prompt(question, documents)},
            ],
        },
        timeout=settings.llm_timeout_seconds,
    )
    resp.raise_for_status()
    data = resp.json()
    return (data["choices"][0]["message"]["content"] or "").strip()


async def _call_anthropic(
    client: httpx.AsyncClient, question: str, documents: list[Document]
) -> str:
    resp = await client.post(
        "https://api.anthropic.com/v1/messages",
        headers={
            "x-api-key": settings.anthropic_api_key or "",
            "anthropic-version": "2023-06-01",
        },
        json={
            "model": settings.anthropic_model,
            "max_tokens": 500,
            "temperature": 0.2,
            "system": SYSTEM_PROMPT,
            "messages": [{"role": "user", "content": build_user_prompt(question, documents)}],
        },
        timeout=settings.llm_timeout_seconds,
    )
    resp.raise_for_status()
    data = resp.json()
    blocks = data.get("content", []) or []
    return "".join(b.get("text", "") for b in blocks if b.get("type") == "text").strip()


def _valid_citations(text: str, source_count: int) -> bool:
    """Reject an answer that cites a source we did not give it."""
    if not text or len(text) < 20:
        return False
    cited = {int(m) for m in _CITATION_RE.findall(text)}
    if not cited:
        return False
    return all(1 <= n <= source_count for n in cited)


async def synthesise(
    client: httpx.AsyncClient,
    question: str,
    documents: list[Document],
) -> Answer:
    """Produce the answer, falling back to extractive on any LLM problem."""
    provider = (settings.answer_provider or "extractive").strip().lower()

    if provider in {"openai", "anthropic"} and documents:
        try:
            if provider == "openai" and settings.openai_api_key:
                text = await _call_openai(client, question, documents)
            elif provider == "anthropic" and settings.anthropic_api_key:
                text = await _call_anthropic(client, question, documents)
            else:
                text = ""

            if _valid_citations(text, len(documents)):
                return Answer(
                    text=text,
                    provider=provider,
                    follow_ups=make_follow_ups(question, documents),
                )
        except (httpx.HTTPError, KeyError, IndexError, ValueError):
            # Fall through to extractive — a broken key must not break search.
            pass

    return Answer(
        text=synthesise_extractive(question, documents),
        provider="extractive",
        follow_ups=make_follow_ups(question, documents),
    )


# --------------------------------------------------------------------------
# follow-up suggestions
# --------------------------------------------------------------------------
def make_follow_ups(question: str, documents: list[Document], *, limit: int = 3) -> list[str]:
    """Suggest next questions grounded in what the sources actually cover.

    Built from the titles of the retrieved pages, so a suggestion is never a
    question the corpus cannot answer.
    """
    suggestions: list[str] = []
    seen: set[str] = set()
    q_lower = question.lower()

    for doc in documents:
        title = normalise(doc.title)
        # Strip site suffixes like " | Reuters" or " - Wikipedia".
        title = re.split(r"\s[|\-–—]\s", title)[0].strip()
        if not title or len(title) < 4:
            continue
        key = title.lower()
        if key in seen or key in q_lower:
            continue
        seen.add(key)

        for template in (
            f"What are the key details of {title}?",
            f"How does {title} work?",
            f"What are the latest developments in {title}?",
        ):
            if template.lower() not in q_lower:
                suggestions.append(template)
                break
        if len(suggestions) >= limit:
            break

    if not suggestions:
        suggestions = [
            "Can you go deeper on that?",
            "What are the counterarguments?",
            "What happened most recently?",
        ]
    return suggestions[:limit]
