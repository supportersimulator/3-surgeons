"""Tests for Complexity Vector Sentinel.

TDD: These tests are written first, before the implementation.
The sentinel monitors project complexity across configurable dimensions
(vectors). Each vector has keywords, a risk score, and a noise threshold.
When complexity exceeds thresholds, sentinel escalates.

Extracted from complexity_vector_sentinel.py (559 lines).
"""
from __future__ import annotations

import pytest

from three_surgeons.core.sentinel import ComplexityVector, Sentinel, SentinelResult


# ── ComplexityVector dataclass ───────────────────────────────────────


class TestComplexityVector:
    def test_fields(self):
        cv = ComplexityVector(
            id="CV-001",
            name="Auth complexity",
            keywords=["auth", "token"],
            risk_score=0.7,
        )
        assert cv.id == "CV-001"
        assert cv.name == "Auth complexity"
        assert cv.keywords == ["auth", "token"]
        assert cv.risk_score == 0.7

    def test_default_noise_threshold(self):
        cv = ComplexityVector(
            id="CV-001", name="Test", keywords=["x"], risk_score=0.5
        )
        assert cv.noise_threshold == 6

    def test_custom_noise_threshold(self):
        cv = ComplexityVector(
            id="CV-001", name="Test", keywords=["x"], risk_score=0.5,
            noise_threshold=10,
        )
        assert cv.noise_threshold == 10


# ── SentinelResult dataclass ─────────────────────────────────────────


class TestSentinelResult:
    def test_fields(self):
        sr = SentinelResult(
            vectors_checked=5,
            vectors_triggered=2,
            risk_level="medium",
            triggered_vectors=[{"id": "CV-001", "name": "Test", "hits": 3}],
            overall_score=0.45,
            recommendations=["Review auth complexity"],
        )
        assert sr.vectors_checked == 5
        assert sr.vectors_triggered == 2
        assert sr.risk_level == "medium"
        assert len(sr.triggered_vectors) == 1
        assert sr.overall_score == 0.45
        assert len(sr.recommendations) == 1

    def test_none_risk_defaults(self):
        sr = SentinelResult(
            vectors_checked=3,
            vectors_triggered=0,
            risk_level="none",
            triggered_vectors=[],
            overall_score=0.0,
            recommendations=[],
        )
        assert sr.risk_level == "none"
        assert sr.overall_score == 0.0


# ── Sentinel class ───────────────────────────────────────────────────


class TestSentinel:
    def test_no_triggers_returns_none_risk(self):
        sentinel = Sentinel()
        result = sentinel.run_cycle("Hello world, simple code")
        assert result.risk_level == "none"
        assert result.vectors_triggered == 0

    def test_keyword_triggers_vector(self):
        vectors = [ComplexityVector(
            id="CV-TEST", name="Test vector",
            keywords=["auth", "token"], risk_score=0.7,
        )]
        sentinel = Sentinel(vectors=vectors)
        result = sentinel.run_cycle("We need to fix the auth token refresh")
        assert result.vectors_triggered == 1
        assert result.risk_level != "none"

    def test_noise_gate_discards_excessive(self):
        vectors = [ComplexityVector(
            id="CV-TEST", name="Noisy vector",
            keywords=["the"], risk_score=0.9, noise_threshold=3,
        )]
        sentinel = Sentinel(vectors=vectors)
        # "the" will appear many times, exceeding noise threshold
        result = sentinel.run_cycle("the the the the the the the the")
        assert result.vectors_triggered == 0  # Noisy, discarded

    def test_risk_level_scoring(self):
        vectors = [ComplexityVector(
            id="CV-SEC", name="Security",
            keywords=["injection", "xss"], risk_score=0.9,
        )]
        sentinel = Sentinel(vectors=vectors)
        result = sentinel.run_cycle("Found SQL injection and XSS vulnerability")
        assert result.risk_level in ("high", "critical")
        assert result.overall_score > 0

    def test_multiple_vectors(self):
        sentinel = Sentinel()  # Use defaults
        content = "The auth token handling has a race condition with the database migration"
        result = sentinel.run_cycle(content)
        assert result.vectors_triggered >= 2
        assert result.vectors_checked == len(sentinel._vectors)

    def test_recommendations_generated(self):
        vectors = [ComplexityVector(
            id="CV-SEC", name="Security",
            keywords=["injection"], risk_score=0.9,
        )]
        sentinel = Sentinel(vectors=vectors)
        result = sentinel.run_cycle("SQL injection risk detected")
        assert len(result.recommendations) > 0

    def test_result_has_triggered_details(self):
        vectors = [ComplexityVector(
            id="CV-TEST", name="Test",
            keywords=["auth"], risk_score=0.5,
        )]
        sentinel = Sentinel(vectors=vectors)
        result = sentinel.run_cycle("auth system needs review")
        assert len(result.triggered_vectors) == 1
        assert result.triggered_vectors[0]["id"] == "CV-TEST"

    def test_default_vectors_loaded(self):
        sentinel = Sentinel()
        assert len(sentinel._vectors) >= 5  # At least 5 defaults

    def test_overall_score_bounded_zero_to_one(self):
        sentinel = Sentinel()
        result = sentinel.run_cycle("auth token injection xss race condition migration cache latency")
        assert 0.0 <= result.overall_score <= 1.0

    def test_risk_level_none_at_zero(self):
        sentinel = Sentinel()
        result = sentinel.run_cycle("nothing relevant here at all")
        assert result.risk_level == "none"
        assert result.overall_score == 0.0

    def test_risk_level_low(self):
        """Score < 0.2 should be 'low'."""
        vectors = [ComplexityVector(
            id="CV-LOW", name="Low risk",
            keywords=["minor"], risk_score=0.1,
        )]
        sentinel = Sentinel(vectors=vectors)
        result = sentinel.run_cycle("a minor issue found")
        assert result.risk_level == "low"

    def test_risk_level_medium(self):
        """Score >= 0.2 and < 0.5 should be 'medium'."""
        vectors = [ComplexityVector(
            id="CV-MED", name="Medium risk",
            keywords=["concern"], risk_score=0.3,
        )]
        sentinel = Sentinel(vectors=vectors)
        result = sentinel.run_cycle("there is a concern here")
        assert result.risk_level == "medium"

    def test_risk_level_high(self):
        """Score >= 0.5 and < 0.8 should be 'high'."""
        vectors = [ComplexityVector(
            id="CV-HIGH", name="High risk",
            keywords=["danger"], risk_score=0.7,
        )]
        sentinel = Sentinel(vectors=vectors)
        result = sentinel.run_cycle("danger zone detected")
        assert result.risk_level == "high"

    def test_risk_level_critical(self):
        """Score >= 0.8 should be 'critical'."""
        vectors = [ComplexityVector(
            id="CV-CRIT", name="Critical risk",
            keywords=["exploit"], risk_score=0.95,
        )]
        sentinel = Sentinel(vectors=vectors)
        result = sentinel.run_cycle("exploit discovered in production")
        assert result.risk_level == "critical"

    def test_case_insensitive_matching(self):
        vectors = [ComplexityVector(
            id="CV-CASE", name="Case test",
            keywords=["auth"], risk_score=0.5,
        )]
        sentinel = Sentinel(vectors=vectors)
        result = sentinel.run_cycle("AUTH system needs review")
        assert result.vectors_triggered == 1

    def test_multi_word_keyword_matching(self):
        """Multi-word keywords like 'race condition' should match."""
        vectors = [ComplexityVector(
            id="CV-MULTI", name="Multi-word",
            keywords=["race condition"], risk_score=0.8,
        )]
        sentinel = Sentinel(vectors=vectors)
        result = sentinel.run_cycle("Found a race condition in the handler")
        assert result.vectors_triggered == 1

    def test_triggered_vector_includes_hit_count(self):
        vectors = [ComplexityVector(
            id="CV-HITS", name="Hit counter",
            keywords=["auth"], risk_score=0.5,
        )]
        sentinel = Sentinel(vectors=vectors)
        result = sentinel.run_cycle("auth auth auth")
        assert result.triggered_vectors[0]["hits"] == 3

    def test_noise_threshold_boundary_included(self):
        """Hits exactly at noise_threshold should still trigger (<=)."""
        vectors = [ComplexityVector(
            id="CV-BOUND", name="Boundary",
            keywords=["word"], risk_score=0.5, noise_threshold=3,
        )]
        sentinel = Sentinel(vectors=vectors)
        result = sentinel.run_cycle("word word word")
        assert result.vectors_triggered == 1

    def test_noise_threshold_boundary_exceeded(self):
        """Hits above noise_threshold should be discarded (>)."""
        vectors = [ComplexityVector(
            id="CV-BOUND", name="Boundary",
            keywords=["word"], risk_score=0.5, noise_threshold=3,
        )]
        sentinel = Sentinel(vectors=vectors)
        result = sentinel.run_cycle("word word word word")
        assert result.vectors_triggered == 0

    def test_optional_state_backend(self):
        """Sentinel should accept optional state backend without error."""
        from three_surgeons.core.state import MemoryBackend
        state = MemoryBackend()
        sentinel = Sentinel(state=state)
        result = sentinel.run_cycle("Hello world")
        assert result.risk_level == "none"

    def test_empty_content(self):
        sentinel = Sentinel()
        result = sentinel.run_cycle("")
        assert result.risk_level == "none"
        assert result.vectors_triggered == 0
        assert result.overall_score == 0.0

    def test_weighted_average_score(self):
        """Overall score should be weighted average of triggered vectors' risk_scores."""
        vectors = [
            ComplexityVector(id="CV-A", name="A", keywords=["alpha"], risk_score=0.4),
            ComplexityVector(id="CV-B", name="B", keywords=["beta"], risk_score=0.8),
            ComplexityVector(id="CV-C", name="C", keywords=["gamma"], risk_score=0.6),
        ]
        sentinel = Sentinel(vectors=vectors)
        # Only alpha and beta trigger
        result = sentinel.run_cycle("alpha beta")
        # Weighted average of 0.4 and 0.8 = 0.6
        assert abs(result.overall_score - 0.6) < 0.01
