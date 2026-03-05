"""Tests for the unified evidence store."""
from __future__ import annotations

from pathlib import Path

import pytest

from three_surgeons.core.evidence import EvidenceStore


class TestEvidenceStore:
    @pytest.fixture
    def store(self, tmp_path: Path) -> EvidenceStore:
        return EvidenceStore(str(tmp_path / "evidence.db"))

    def test_record_learning(self, store: EvidenceStore) -> None:
        store.record_learning(
            title="Redis locks prevent GPU stampede",
            content="File-based fallback when Redis unavailable",
            learning_type="fix",
            tags=["gpu", "redis", "lock"],
        )
        results = store.search("GPU lock")
        assert len(results) >= 1
        assert "Redis" in results[0]["title"]

    def test_record_cross_exam(self, store: EvidenceStore) -> None:
        store.record_cross_exam(
            topic="Should we use SQLite?",
            neurologist_report="SQLite is good for single-user",
            cardiologist_report="Consider Postgres for multi-user",
            consensus_score=0.7,
        )
        exams = store.get_cross_exams(limit=5)
        assert len(exams) == 1
        assert exams[0]["topic"] == "Should we use SQLite?"

    def test_track_cost(self, store: EvidenceStore) -> None:
        store.track_cost("cardiologist", 0.004, "cross-exam query")
        store.track_cost("cardiologist", 0.002, "consensus query")
        total = store.get_daily_cost("cardiologist")
        assert abs(total - 0.006) < 0.0001

    def test_fts_search(self, store: EvidenceStore) -> None:
        store.record_learning("Alpha fix", "Fixed alpha bug", "fix", ["alpha"])
        store.record_learning("Beta feature", "Added beta feature", "win", ["beta"])
        results = store.search("alpha")
        assert len(results) == 1
        assert results[0]["title"] == "Alpha fix"

    def test_get_stats(self, store: EvidenceStore) -> None:
        store.record_learning("Fix 1", "content", "fix", [])
        store.record_learning("Win 1", "content", "win", [])
        stats = store.get_stats()
        assert stats["total"] == 2
        assert stats["fixes"] == 1
        assert stats["wins"] == 1


class TestCrossExamOrdering:
    """Cross-exams return most recent first."""

    @pytest.fixture
    def store(self, tmp_path: Path) -> EvidenceStore:
        return EvidenceStore(str(tmp_path / "evidence.db"))

    def test_cross_exams_ordered_newest_first(self, store: EvidenceStore) -> None:
        store.record_cross_exam("First", "n1", "c1", 0.5)
        store.record_cross_exam("Second", "n2", "c2", 0.8)
        exams = store.get_cross_exams(limit=5)
        assert len(exams) == 2
        assert exams[0]["topic"] == "Second"
        assert exams[1]["topic"] == "First"


class TestCostTracking:
    """Cost tracking edge cases."""

    @pytest.fixture
    def store(self, tmp_path: Path) -> EvidenceStore:
        return EvidenceStore(str(tmp_path / "evidence.db"))

    def test_daily_cost_zero_for_unknown_surgeon(self, store: EvidenceStore) -> None:
        total = store.get_daily_cost("unknown_surgeon")
        assert total == 0.0

    def test_costs_separate_by_surgeon(self, store: EvidenceStore) -> None:
        store.track_cost("cardiologist", 0.01, "query")
        store.track_cost("neurologist", 0.002, "query")
        assert abs(store.get_daily_cost("cardiologist") - 0.01) < 0.0001
        assert abs(store.get_daily_cost("neurologist") - 0.002) < 0.0001


class TestABResults:
    """A/B experiment result recording."""

    @pytest.fixture
    def store(self, tmp_path: Path) -> EvidenceStore:
        return EvidenceStore(str(tmp_path / "evidence.db"))

    def test_record_ab_result(self, store: EvidenceStore) -> None:
        store.record_ab_result(
            experiment_id="exp-001",
            param="temperature",
            variant_a="0.3",
            variant_b="0.7",
            verdict="variant_a wins on coherence",
        )
        # Verify via stats or snapshot that it was stored
        snapshot = store.get_evidence_snapshot("temperature")
        assert "exp-001" in snapshot["evidence_text"]


class TestObservations:
    """Observation recording."""

    @pytest.fixture
    def store(self, tmp_path: Path) -> EvidenceStore:
        return EvidenceStore(str(tmp_path / "evidence.db"))

    def test_record_observation(self, store: EvidenceStore) -> None:
        store.record_observation(
            statement="FTS5 performs well under 100k rows",
            confidence=0.9,
            evidence_grade="empirical",
        )
        snapshot = store.get_evidence_snapshot("FTS5")
        assert "FTS5" in snapshot["evidence_text"]


class TestEvidenceSnapshot:
    """Evidence snapshot aggregation."""

    @pytest.fixture
    def store(self, tmp_path: Path) -> EvidenceStore:
        return EvidenceStore(str(tmp_path / "evidence.db"))

    def test_snapshot_includes_learnings(self, store: EvidenceStore) -> None:
        store.record_learning(
            "WAL mode helps concurrency",
            "SQLite WAL allows concurrent reads",
            "pattern",
            ["sqlite", "wal"],
        )
        snapshot = store.get_evidence_snapshot("WAL")
        assert len(snapshot["learnings"]) >= 1
        assert "stats" in snapshot
        assert "evidence_text" in snapshot

    def test_snapshot_empty_topic(self, store: EvidenceStore) -> None:
        snapshot = store.get_evidence_snapshot("nonexistent_xyz")
        assert snapshot["learnings"] == []
        assert snapshot["stats"]["total"] == 0

    def test_snapshot_respects_limit(self, store: EvidenceStore) -> None:
        for i in range(10):
            store.record_learning(f"Topic item {i}", f"Content about topic {i}", "fix", ["topic"])
        snapshot = store.get_evidence_snapshot("topic", limit=3)
        assert len(snapshot["learnings"]) == 3


class TestSearchEdgeCases:
    """FTS search edge cases."""

    @pytest.fixture
    def store(self, tmp_path: Path) -> EvidenceStore:
        return EvidenceStore(str(tmp_path / "evidence.db"))

    def test_search_returns_empty_for_no_match(self, store: EvidenceStore) -> None:
        store.record_learning("Something", "Content", "fix", [])
        results = store.search("zzz_nonexistent_zzz")
        assert results == []

    def test_search_limit(self, store: EvidenceStore) -> None:
        for i in range(10):
            store.record_learning(f"Item {i}", f"Shared keyword content", "fix", [])
        results = store.search("keyword", limit=3)
        assert len(results) == 3
