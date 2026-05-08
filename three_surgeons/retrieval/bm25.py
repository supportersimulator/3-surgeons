"""Pure-Python Okapi BM25 over an in-memory corpus.

Ported from IJFW's ``mcp-server/src/search-bm25.js`` per the harvest plan
(2026-04-25 ContextDNA strategic doc).

WHY THIS EXISTS
---------------
3-Surgeons needs a warm-tier retrieval layer for prior consults, surgeon
verdicts, evidence packets, and decision rationale — without dragging in
SQLite FTS5, a vector DB, or a native dependency.

This module is a *fast first pass*. Above ~10 K documents the linear scan
starts to hurt; in that regime the caller should layer this behind a
chunked store or graduate to a proper inverted index.

DESIGN
------
* No I/O, no global state.
* :func:`search_corpus` accepts a list of ``{"id", "text", "meta"}`` dicts
  (or any objects exposing those keys via :py:meth:`__getitem__`).
* Standard Okapi BM25 with ``k1=1.2``, ``b=0.75`` — same defaults as IJFW
  and SQLite FTS5.
* Quoted phrases in the query enforce substring containment AND contribute
  scaled IDF to the score (matches IJFW behaviour).
* Returns ranked list with ``score`` and short ``snippet`` for UI panels.

NOT GOALS
---------
* Not a stemmer (e.g. "user", "users" treated as different tokens).
* Not multilingual — ASCII tokenisation only.
* Not the source of truth for evidence — that's the receipts JSONL +
  ContextDNA chief memory.
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass
from typing import Any, Iterable, Sequence

#: Stop-words copied from IJFW search-bm25.js. Intentionally narrow —
#: domain-specific stop-words should be added by the caller, not here.
STOPWORDS: frozenset[str] = frozenset({
    "a", "an", "the", "is", "are", "was", "were", "be", "been", "being",
    "do", "does", "did", "of", "in", "on", "at", "to", "for", "with", "by",
    "from", "as", "that", "this", "it", "and", "or", "but", "if", "so",
    "not", "no", "yes", "we", "i", "you", "they", "he", "she",
})

# Token: 2+ chars of [a-z0-9_-.] after lower-casing and replacing all other
# chars with whitespace. Mirrors the IJFW regex.
_TOKEN_STRIP = re.compile(r"[^a-z0-9_\-.\s]")
_PHRASE_RE = re.compile(r'"([^"]+)"')


def tokenize(text: str | Any) -> list[str]:
    """Lower-case, strip punctuation, drop stop-words and 1-char tokens."""
    if not isinstance(text, str) or not text:
        return []
    cleaned = _TOKEN_STRIP.sub(" ", text.lower())
    return [
        t for t in cleaned.split()
        if t and len(t) >= 2 and t not in STOPWORDS
    ]


def _extract_phrases(query: str) -> list[str]:
    """Pull quoted phrases out of the query (lower-cased)."""
    return [m.group(1).lower() for m in _PHRASE_RE.finditer(query)]


@dataclass(frozen=True)
class ScoredDoc:
    """One row of search output."""
    id: str
    score: float
    meta: Any
    snippet: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id, "score": self.score,
            "meta": self.meta, "snippet": self.snippet,
        }


def _doc_field(doc: Any, field: str, default: Any = None) -> Any:
    """Read a field from either a dict or an object exposing __getitem__."""
    if isinstance(doc, dict):
        return doc.get(field, default)
    try:
        return doc[field]
    except (KeyError, TypeError):
        return getattr(doc, field, default)


def _make_snippet(text: str, q_tokens: Sequence[str], width: int = 160) -> str:
    """Window of ``width`` chars around the first matched query token."""
    if not text:
        return ""
    lower = text.lower()
    best_pos = -1
    for t in q_tokens:
        p = lower.find(t)
        if p >= 0 and (best_pos < 0 or p < best_pos):
            best_pos = p
    if best_pos < 0:
        # No token match — fall back to text head.
        return re.sub(r"\s+", " ", text[:width])
    start = max(0, best_pos - 40)
    end = min(len(text), start + width)
    prefix = "…" if start > 0 else ""
    suffix = "…" if end < len(text) else ""
    return prefix + re.sub(r"\s+", " ", text[start:end]) + suffix


def search_corpus(
    query: str,
    docs: Iterable[Any],
    *,
    k1: float = 1.2,
    b: float = 0.75,
    limit: int = 10,
) -> list[ScoredDoc]:
    """Okapi BM25 search over ``docs``.

    ``docs`` is iterated once and converted to a list internally.

    Phrase semantics: any quoted ``"phrase"`` in ``query`` is required as
    a substring; documents missing any required phrase are filtered before
    scoring. Phrase tokens still contribute (at half weight) to the score
    of documents that pass the filter.
    """
    if not query:
        return []
    docs_list = list(docs)
    if not docs_list:
        return []

    phrases = _extract_phrases(query)
    bare_query = _PHRASE_RE.sub(" ", query)
    q_tokens = tokenize(bare_query)
    if not q_tokens and not phrases:
        return []

    doc_tokens = [tokenize(_doc_field(d, "text", "") or "") for d in docs_list]
    doc_lens = [len(t) for t in doc_tokens]
    avg_dl = sum(doc_lens) / max(1, len(doc_lens))

    # Document frequencies for query tokens.
    df: dict[str, int] = {}
    for t in q_tokens:
        if t in df:
            continue
        df[t] = sum(1 for tokens in doc_tokens if t in tokens)
    # Document frequencies for phrase tokens (computed lazily later).
    n = len(docs_list)

    scored: list[ScoredDoc] = []
    for i, doc in enumerate(docs_list):
        text_field = str(_doc_field(doc, "text", "") or "")
        lower_text = text_field.lower()
        if not all(p in lower_text for p in phrases):
            continue

        d_len = doc_lens[i]
        # Term frequencies for this doc.
        tf: dict[str, int] = {}
        for t in doc_tokens[i]:
            tf[t] = tf.get(t, 0) + 1

        score = 0.0
        for t in q_tokens:
            f = tf.get(t)
            if not f:
                continue
            doc_count = df.get(t, 0)
            idf = math.log(1 + (n - doc_count + 0.5) / (doc_count + 0.5))
            denom = f + k1 * (1 - b + (b * d_len) / (avg_dl or 1))
            score += idf * ((f * (k1 + 1)) / denom)

        for p in phrases:
            phrase_tokens = tokenize(p)
            for t in phrase_tokens:
                doc_count = df.get(t)
                if doc_count is None:
                    doc_count = sum(1 for ts in doc_tokens if t in ts)
                idf = math.log(1 + (n - doc_count + 0.5) / (doc_count + 0.5))
                score += idf * 0.5

        if score > 0:
            scored.append(ScoredDoc(
                id=str(_doc_field(doc, "id", "")),
                score=score,
                meta=_doc_field(doc, "meta"),
                snippet=_make_snippet(text_field, q_tokens),
            ))

    scored.sort(key=lambda d: d.score, reverse=True)
    return scored[:limit]


__all__ = ["STOPWORDS", "tokenize", "search_corpus", "ScoredDoc"]
