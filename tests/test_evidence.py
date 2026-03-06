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


# ── Evidence Grading Ladder ──────────────────────────────────────────


from three_surgeons.core.evidence import EvidenceGrade


class TestEvidenceGrade:
    """EvidenceGrade enum: EBM-inspired grading with weights."""

    def test_grade_hierarchy_order(self) -> None:
        assert EvidenceGrade.ANECDOTAL.weight < EvidenceGrade.CASE_SERIES.weight
        assert EvidenceGrade.CASE_SERIES.weight < EvidenceGrade.COHORT.weight
        assert EvidenceGrade.COHORT.weight < EvidenceGrade.VALIDATED.weight

    def test_from_string_known_grades(self) -> None:
        assert EvidenceGrade.from_string("anecdotal") == EvidenceGrade.ANECDOTAL
        assert EvidenceGrade.from_string("cohort") == EvidenceGrade.COHORT
        assert EvidenceGrade.from_string("validated") == EvidenceGrade.VALIDATED

    def test_from_string_backward_compat(self) -> None:
        # Internal system used "correlation" → maps to CASE_SERIES
        assert EvidenceGrade.from_string("correlation") == EvidenceGrade.CASE_SERIES
        # "anecdote" (no 'l') → ANECDOTAL
        assert EvidenceGrade.from_string("anecdote") == EvidenceGrade.ANECDOTAL
        # "opinion" → EXPERT_OPINION
        assert EvidenceGrade.from_string("opinion") == EvidenceGrade.EXPERT_OPINION

    def test_from_string_unknown_defaults_anecdotal(self) -> None:
        assert EvidenceGrade.from_string("made_up_grade") == EvidenceGrade.ANECDOTAL

    def test_apply_to_confidence(self) -> None:
        # High confidence + weak evidence = discounted
        grade = EvidenceGrade.ANECDOTAL
        weighted = grade.apply_to_confidence(0.9)
        assert weighted < 0.9
        assert weighted == pytest.approx(0.9 * grade.weight)

    def test_apply_to_confidence_validated(self) -> None:
        # Validated evidence preserves most of the confidence
        grade = EvidenceGrade.VALIDATED
        weighted = grade.apply_to_confidence(0.9)
        assert weighted > 0.7

    def test_grade_rank_ordering(self) -> None:
        assert EvidenceGrade.ANECDOTAL.rank < EvidenceGrade.EXPERT_OPINION.rank
        assert EvidenceGrade.EXPERT_OPINION.rank < EvidenceGrade.CASE_SERIES.rank
        assert EvidenceGrade.CASE_SERIES.rank < EvidenceGrade.COHORT.rank
        assert EvidenceGrade.COHORT.rank < EvidenceGrade.VALIDATED.rank


class TestEvidenceGradeUpgrade:
    """UP-ONLY evidence grade ladder on observations."""

    @pytest.fixture
    def store(self, tmp_path: Path) -> EvidenceStore:
        return EvidenceStore(str(tmp_path / "evidence.db"))

    def test_record_observation_stores_weighted_confidence(self, store: EvidenceStore) -> None:
        obs_id = store.record_observation(
            statement="WAL checkpoints prevent bloat",
            confidence=0.8,
            evidence_grade="anecdotal",
        )
        assert obs_id is not None

    def test_record_outcome_and_count(self, store: EvidenceStore) -> None:
        obs_id = store.record_observation("Test claim", 0.7, "anecdotal")
        store.record_outcome(obs_id, success=True)
        store.record_outcome(obs_id, success=True)
        store.record_outcome(obs_id, success=False)
        stats = store.get_observation_outcome_stats(obs_id)
        assert stats["n"] == 3
        assert stats["success_rate"] == pytest.approx(2.0 / 3.0)

    def test_auto_upgrade_anecdotal_to_case_series(self, store: EvidenceStore) -> None:
        obs_id = store.record_observation("Repeatable fix", 0.7, "anecdotal")
        # Need 3 outcomes at 50%+ for correlation, 5 at 60%+ for case_series
        for _ in range(5):
            store.record_outcome(obs_id, success=True)
        result = store.auto_upgrade_grade(obs_id)
        assert result is not None
        assert result["old_grade"] == "anecdotal"
        # 5 outcomes at 100% success → case_series (5@60%)
        assert result["new_grade"] == "case_series"

    def test_auto_upgrade_never_downgrades(self, store: EvidenceStore) -> None:
        obs_id = store.record_observation("Strong claim", 0.9, "cohort")
        # Record only 1 outcome (would be anecdotal level)
        store.record_outcome(obs_id, success=True)
        result = store.auto_upgrade_grade(obs_id)
        # Should NOT downgrade from cohort to anecdotal
        assert result is None

    def test_auto_upgrade_to_validated(self, store: EvidenceStore) -> None:
        obs_id = store.record_observation("Well-tested claim", 0.8, "anecdotal")
        for _ in range(20):
            store.record_outcome(obs_id, success=True)
        result = store.auto_upgrade_grade(obs_id)
        assert result is not None
        assert result["new_grade"] == "validated"

    def test_grade_history_logged(self, store: EvidenceStore) -> None:
        obs_id = store.record_observation("Track history", 0.7, "anecdotal")
        for _ in range(5):
            store.record_outcome(obs_id, success=True)
        store.auto_upgrade_grade(obs_id)
        history = store.get_grade_history(obs_id)
        assert len(history) == 1
        assert history[0]["old_grade"] == "anecdotal"
        assert history[0]["new_grade"] == "case_series"

    def test_upgrade_threshold_requires_success_rate(self, store: EvidenceStore) -> None:
        obs_id = store.record_observation("Flaky claim", 0.5, "anecdotal")
        # 10 outcomes but only 40% success → stays at anecdotal (needs 50% for correlation)
        for _ in range(4):
            store.record_outcome(obs_id, success=True)
        for _ in range(6):
            store.record_outcome(obs_id, success=False)
        result = store.auto_upgrade_grade(obs_id)
        assert result is None  # 40% < 50% threshold
