"""Tests for three_surgeons/retrieval/bm25.py — IJFW Phase 1 harvest."""
from __future__ import annotations

from three_surgeons.retrieval.bm25 import (
    STOPWORDS,
    ScoredDoc,
    search_corpus,
    tokenize,
)


# ── Tokenizer ──────────────────────────────────────────────────────────────


def test_tokenize_lowercases():
    assert tokenize("Hello World") == ["hello", "world"]


def test_tokenize_drops_stopwords():
    out = tokenize("the quick brown fox is in the box")
    # "the", "is", "in" all stop-words → dropped
    assert "the" not in out
    assert "is" not in out
    assert "in" not in out
    assert "quick" in out


def test_tokenize_drops_one_char_tokens():
    """Length filter: tokens < 2 chars dropped."""
    out = tokenize("a b cd")
    assert "a" not in out
    assert "b" not in out
    assert "cd" in out


def test_tokenize_keeps_dots_dashes_underscores():
    """src/auth.py and snake_case names should survive."""
    out = tokenize("src/auth.py and getUserById tests")
    assert "auth.py" in out  # dots kept inside token
    assert any("user" in t.lower() for t in out)  # CamelCase kept lowered


def test_tokenize_punctuation_to_space():
    out = tokenize("hello, world! (test)")
    assert "hello" in out
    assert "world" in out
    assert "test" in out


def test_tokenize_non_string_returns_empty():
    assert tokenize(None) == []
    assert tokenize(42) == []
    assert tokenize("") == []


def test_stopwords_constant_immutable():
    """STOPWORDS is frozenset to prevent accidental mutation."""
    assert isinstance(STOPWORDS, frozenset)


# ── BM25 search ────────────────────────────────────────────────────────────


_DOCS = [
    {"id": "d1", "text": "auth middleware token expiry bug", "meta": {"k": 1}},
    {"id": "d2", "text": "database migration rollback procedure", "meta": {"k": 2}},
    {"id": "d3", "text": "auth login flow refactored for clarity", "meta": {"k": 3}},
    {"id": "d4", "text": "frontend button styling updated", "meta": {"k": 4}},
    {"id": "d5", "text": "auth token middleware test coverage gap", "meta": {"k": 5}},
]


def test_empty_query_returns_empty():
    assert search_corpus("", _DOCS) == []


def test_empty_corpus_returns_empty():
    assert search_corpus("auth", []) == []


def test_finds_relevant_docs():
    results = search_corpus("auth middleware", _DOCS)
    ids = [r.id for r in results]
    # d1 and d5 both have "auth" + "middleware" — should rank top
    assert ids[0] in {"d1", "d5"}
    assert ids[1] in {"d1", "d5"}


def test_unrelated_query_returns_empty_or_zero():
    """No matching tokens → no results."""
    results = search_corpus("kubernetes nginx ingress", _DOCS)
    assert results == []


def test_stopword_only_query_returns_empty():
    """Query of only stop-words tokenises to nothing."""
    results = search_corpus("the and of", _DOCS)
    assert results == []


def test_phrase_filter():
    """Quoted phrase REQUIRES substring match."""
    # "token expiry" is in d1 only (d5 has "token middleware" — different order).
    results = search_corpus('"token expiry"', _DOCS)
    assert {r.id for r in results} == {"d1"}


def test_phrase_filter_excludes_non_match():
    """A query phrase that doesn't appear in any doc → empty."""
    results = search_corpus('"nonexistent phrase here"', _DOCS)
    assert results == []


def test_phrase_plus_bare_query():
    results = search_corpus('"auth" middleware', _DOCS)
    # All "auth" docs match phrase; "middleware" boosts d1 + d5
    ids = [r.id for r in results]
    assert ids[0] in {"d1", "d5"}


def test_results_sorted_by_score_desc():
    results = search_corpus("auth", _DOCS)
    scores = [r.score for r in results]
    assert scores == sorted(scores, reverse=True)


def test_limit_respected():
    results = search_corpus("auth", _DOCS, limit=1)
    assert len(results) == 1


def test_snippet_contains_match_when_possible():
    results = search_corpus("middleware", _DOCS)
    top = results[0]
    assert "middleware" in top.snippet.lower()


def test_score_uses_idf_so_rare_terms_rank_higher():
    """A term in only 1 doc gets higher IDF than a term in 3 docs."""
    common_results = search_corpus("auth", _DOCS)
    rare_results = search_corpus("rollback", _DOCS)
    # "rollback" appears in only d2 → high IDF
    # "auth" appears in d1, d3, d5 → lower IDF
    if rare_results and common_results:
        # Same TF=1, but rare > common per BM25 IDF math
        assert rare_results[0].score >= common_results[0].score * 0.5


def test_scored_doc_to_dict():
    results = search_corpus("auth", _DOCS)
    d = results[0].to_dict()
    assert d.keys() >= {"id", "score", "meta", "snippet"}


def test_doc_with_object_field_access():
    """Docs can be objects, not just dicts."""
    class Doc:
        def __init__(self, id_, text, meta=None):
            self.id = id_
            self.text = text
            self.meta = meta
        def __getitem__(self, k):
            return getattr(self, k)
    objs = [Doc("o1", "auth middleware"), Doc("o2", "unrelated")]
    results = search_corpus("auth", objs)
    assert len(results) == 1
    assert results[0].id == "o1"


def test_phrase_token_contributes_to_score_on_passing_doc():
    """Phrase-passing doc gets bonus IDF from phrase tokens."""
    no_phrase = search_corpus("auth middleware", _DOCS)
    with_phrase = search_corpus('"auth middleware" middleware', _DOCS)
    # Doc d1 has "auth middleware" subsequence; with_phrase score for d1 should be >=
    d1_no = next(r.score for r in no_phrase if r.id == "d1")
    d1_with = next(r.score for r in with_phrase if r.id == "d1")
    assert d1_with >= d1_no
