"""Text utilities: tokenising, sentence splitting, scoring, passage selection.

Deliberately dependency-free. A search engine's ranking is the product, so it
lives in readable code rather than behind a library call.
"""

from __future__ import annotations

import math
import re
from collections import Counter

# Words that carry no signal when matching a question to a document.
STOPWORDS = frozenset(
    [
        "a",
        "an",
        "the",
        "and",
        "or",
        "but",
        "if",
        "then",
        "than",
        "that",
        "this",
        "these",
        "those",
        "of",
        "in",
        "on",
        "at",
        "to",
        "for",
        "from",
        "by",
        "with",
        "without",
        "into",
        "onto",
        "about",
        "as",
        "is",
        "are",
        "was",
        "were",
        "be",
        "been",
        "being",
        "am",
        "do",
        "does",
        "did",
        "doing",
        "have",
        "has",
        "had",
        "having",
        "i",
        "you",
        "he",
        "she",
        "it",
        "we",
        "they",
        "me",
        "him",
        "her",
        "them",
        "my",
        "your",
        "his",
        "its",
        "our",
        "their",
        "what",
        "which",
        "who",
        "whom",
        "whose",
        "when",
        "where",
        "why",
        "how",
        "can",
        "could",
        "should",
        "would",
        "will",
        "shall",
        "may",
        "might",
        "must",
        "not",
        "no",
        "nor",
        "so",
        "such",
        "very",
        "too",
        "also",
        "just",
        "only",
        "own",
        "same",
        "other",
        "some",
        "any",
        "all",
        "both",
        "each",
        "few",
        "more",
        "most",
        "there",
        "here",
        "up",
        "down",
        "out",
        "over",
        "under",
        "again",
        "further",
        "once",
        "s",
        "t",
        "don",
        "now",
    ]
)

_WORD_RE = re.compile(r"[a-z0-9][a-z0-9'\-]*", re.IGNORECASE)
_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9\"'(])")
_WS = re.compile(r"\s+")

# Figure captions and table labels read like sentences but carry no answer.
# They are short, start with a noun phrase, and have no finite verb.
_CAPTION_START = re.compile(
    r"^(?:schematic|diagram|figure|fig\.|image|photo|graph|chart|table|map|"
    r"illustration|composite|montage|close-?up|screenshot|portrait|demo|"
    r"representation|chart showing|a diagram|an illustration|source:|credit:)\b",
    re.IGNORECASE,
)

# "... image showing ...", "... diagram of ..." anywhere near the start is a
# caption even when the first word is not one of the words above.
_CAPTION_PHRASE = re.compile(
    r"^[^.]{0,60}\b(?:image|diagram|photograph|screenshot|illustration)\s+"
    r"(?:showing|of|depicting|illustrating)\b",
    re.IGNORECASE,
)

# A crude finite-verb probe. Not linguistics — just enough to tell prose from a
# label. Any of these appearing means the sentence is probably a real clause.
_VERB_HINT = re.compile(
    r"\b(?:is|are|was|were|be|been|being|has|have|had|do|does|did|can|could|"
    r"will|would|shall|should|may|might|must|uses?|used|makes?|made|"
    r"provides?|allows?|enables?|means?|refers?|describes?|contains?|"
    r"includes?|occurs?|happens?|becomes?|gives?|takes?|comes?|goes?|"
    r"shows?|known|named|called|considered|regarded|consists?|involves?|"
    r"stores?|supports?|converts?|releases?|learns?|builds?|represents?|"
    r"defines?|produces?|creates?|requires?|depends?|appears?|exists?|"
    r"remains?|follows?|leads?|serves?|functions?|works?|helps?|adds?|"
    r"sets?|gets?|puts?|finds?|keeps?|holds?|runs?|starts?|ends?|begins?|"
    r"continues?|returns?|generalises?|generalizes?|measures?|tracks?)\b",
    re.IGNORECASE,
)

# Suffixes that mark a verb form the word list above will miss.
_STRONG_VERB_SUFFIX = ("ed", "ing", "ise", "ize", "ate", "ify", "fy")


def _has_verb_signal(sentence: str) -> bool:
    """Best-effort "is this a clause or a label?" check.

    Deliberately not a parser. Two signals, in order of confidence:

    1. A word from the verb list, or a word with a strong verb suffix
       (-ed, -ing, -ise, -ate, -ify) anywhere in the sentence.
    2. A word ending in -s/-es, but only if it is *not* the final word. A
       trailing plural noun is how captions end ("...in plants"), while a
       third-person verb sits mid-clause ("It builds models from data").
    """
    if _VERB_HINT.search(sentence):
        return True

    words = _WORD_RE.findall(sentence)
    if not words:
        return False

    for word in words:
        lowered = word.lower()
        if len(lowered) >= 5 and lowered.endswith(_STRONG_VERB_SUFFIX):
            return True

    for word in words[:-1]:
        lowered = word.lower()
        if len(lowered) >= 4 and lowered.endswith(("s", "es")):
            return True

    return False


def normalise(text: str) -> str:
    return _WS.sub(" ", text).strip()


def tokenize(text: str, *, keep_stopwords: bool = False) -> list[str]:
    """Lowercase word tokens. Stopwords dropped unless asked for."""
    tokens = [t.lower() for t in _WORD_RE.findall(text)]
    if keep_stopwords:
        return tokens
    return [t for t in tokens if t not in STOPWORDS and len(t) > 1]


def split_sentences(text: str) -> list[str]:
    """Split prose into sentences, keeping it simple and predictable.

    Also drops figure captions and bare labels, which otherwise win passage
    selection on short factual questions ("Schematic of photosynthesis in
    plants." matches every keyword and answers nothing).
    """
    text = normalise(text)
    if not text:
        return []
    parts = _SENTENCE_SPLIT.split(text)
    out: list[str] = []
    for part in parts:
        part = part.strip()
        # Very short fragments are usually nav junk or list bullets. The floor
        # is low on purpose: "It builds models from data." is 26 chars and is a
        # perfectly good sentence.
        if len(part) < 20:
            continue
        if _CAPTION_START.match(part):
            continue
        if _CAPTION_PHRASE.match(part):
            continue
        # A short sentence with no verb at all is a label, not a claim.
        if len(part) < 130 and not _has_verb_signal(part):
            continue
        out.append(part)
    return out


def bm25_scores(
    query_tokens: list[str],
    documents: list[list[str]],
    *,
    k1: float = 1.5,
    b: float = 0.75,
) -> list[float]:
    """Okapi BM25 over an in-memory corpus.

    Used to rank candidate sentences inside one page, and to rank pages against
    each other. Small corpus, so the full formula is cheap.
    """
    if not documents or not query_tokens:
        return [0.0] * len(documents)

    n_docs = len(documents)
    avg_len = sum(len(d) for d in documents) / n_docs or 1.0

    # Document frequency per query term.
    df: Counter[str] = Counter()
    for doc in documents:
        for term in set(doc):
            df[term] += 1

    idf: dict[str, float] = {}
    for term in set(query_tokens):
        freq = df.get(term, 0)
        # BM25's probabilistic idf, floored so a term in every doc still counts.
        idf[term] = max(0.0, math.log(1 + (n_docs - freq + 0.5) / (freq + 0.5)))

    scores: list[float] = []
    for doc in documents:
        length = len(doc) or 1
        tf = Counter(doc)
        score = 0.0
        for term in query_tokens:
            if term not in tf:
                continue
            freq = tf[term]
            denom = freq + k1 * (1 - b + b * (length / avg_len))
            score += idf.get(term, 0.0) * (freq * (k1 + 1)) / (denom or 1)
        scores.append(score)
    return scores


def coverage(query_tokens: list[str], text: str) -> float:
    """Fraction of distinct query terms present in `text`, 0..1.

    BM25 rewards repetition; coverage rewards actually addressing the question.
    The two are blended when ranking.
    """
    if not query_tokens:
        return 0.0
    wanted = set(query_tokens)
    present = wanted & set(tokenize(text))
    return len(present) / len(wanted)


def select_passages(
    question: str,
    sentences: list[str],
    *,
    limit: int = 4,
    min_score: float = 0.0,
) -> list[str]:
    """Pick the sentences that best answer `question`.

    Ranks with BM25 over sentences, then blends in query coverage so a sentence
    that mentions every part of the question beats one that hammers a single
    keyword. Original document order is restored in the output so the answer
    reads naturally.
    """
    if not sentences:
        return []

    q_tokens = tokenize(question)
    if not q_tokens:
        return sentences[:limit]

    tokenised = [tokenize(s) for s in sentences]
    bm25 = bm25_scores(q_tokens, tokenised)

    scored: list[tuple[float, int]] = []
    for idx, (sentence, tokens) in enumerate(zip(sentences, tokenised, strict=True)):
        if not tokens:
            continue
        cov = coverage(q_tokens, sentence)
        # Normalise BM25 into 0..1 so the blend is meaningful.
        norm_bm25 = bm25[idx] / (bm25[idx] + 3.0) if bm25[idx] > 0 else 0.0
        score = 0.6 * norm_bm25 + 0.4 * cov
        if score > min_score:
            scored.append((score, idx))

    if not scored:
        return sentences[:limit]

    scored.sort(key=lambda pair: pair[0], reverse=True)
    chosen = sorted(idx for _, idx in scored[:limit])
    return [sentences[i] for i in chosen]


def truncate(text: str, limit: int, *, suffix: str = "…") -> str:
    """Trim on a word boundary so snippets never cut mid-word."""
    text = normalise(text)
    if len(text) <= limit:
        return text
    cut = text[:limit].rsplit(" ", 1)[0]
    return (cut or text[:limit]).rstrip(",;:") + suffix


def slugify(text: str, *, max_length: int = 60) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return slug[:max_length].strip("-") or "search"
