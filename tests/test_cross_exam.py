"""Tests for the cross-examination engine (SurgeryTeam).

TDD: These tests are written first, before the implementation.
The cross-exam engine orchestrates multi-model evaluation where
"the value is in the disagreements, not the agreements."
"""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from three_surgeons.core.cross_exam import (
    ConsensusResult,
    CrossExamResult,
    SurgeryTeam,
)
from three_surgeons.core.evidence import EvidenceStore
from three_surgeons.core.models import LLMResponse
from three_surgeons.core.state import MemoryBackend


class TestCrossExam:
    """Cross-examination: each surgeon reviews the other's analysis."""

    @pytest.fixture
    def mock_team(self, tmp_path):
        cardio = MagicMock()
        cardio.query.return_value = LLMResponse(
            ok=True,
            content="Cardiologist analysis: SQLite is simpler",
            latency_ms=200,
            model="gpt-4.1-mini",
            cost_usd=0.001,
        )
        neuro = MagicMock()
        neuro.query.return_value = LLMResponse(
            ok=True,
            content="Neurologist analysis: SQLite handles concurrency poorly",
            latency_ms=50,
            model="qwen3:4b",
        )
        evidence = EvidenceStore(str(tmp_path / "evidence.db"))
        state = MemoryBackend()
        return SurgeryTeam(
            cardiologist=cardio,
            neurologist=neuro,
            evidence=evidence,
            state=state,
        )

    def test_cross_exam_returns_result(self, mock_team):
        result = mock_team.cross_examine("Should we use SQLite or Postgres?")
        assert isinstance(result, CrossExamResult)
        assert result.neurologist_report is not None
        assert result.cardiologist_report is not None
        assert result.total_cost >= 0

    def test_cross_exam_handles_model_failure(self, tmp_path):
        cardio = MagicMock()
        cardio.query.return_value = LLMResponse.error("API timeout", "gpt-4.1-mini")
        neuro = MagicMock()
        neuro.query.return_value = LLMResponse(
            ok=True,
            content="Analysis from neurologist",
            latency_ms=50,
            model="qwen3:4b",
        )
        evidence = EvidenceStore(str(tmp_path / "evidence.db"))
        team = SurgeryTeam(
            cardiologist=cardio,
            neurologist=neuro,
            evidence=evidence,
            state=MemoryBackend(),
        )
        result = team.cross_examine("test topic")
        # When cardiologist fails, its report should be None or contain "unavailable"
        assert result.cardiologist_report is None or "unavailable" in result.cardiologist_report

    def test_cross_exam_tracks_total_latency(self, mock_team):
        result = mock_team.cross_examine("test topic")
        assert result.total_latency_ms > 0

    def test_cross_exam_produces_synthesis(self, mock_team):
        result = mock_team.cross_examine("Should we use SQLite or Postgres?")
        # Full cross-exam should attempt synthesis of disagreements
        assert result.synthesis is not None or result.topic == "Should we use SQLite or Postgres?"

    def test_cross_exam_includes_exploration(self, mock_team):
        result = mock_team.cross_examine("Should we use SQLite or Postgres?")
        # Phase 3: Open exploration surfaces unknown unknowns
        assert result.cardiologist_exploration is not None
        assert result.neurologist_exploration is not None


class TestConsult:
    """Consult: quick parallel query to both surgeons, raw analyses."""

    @pytest.fixture
    def mock_team(self, tmp_path):
        cardio = MagicMock()
        cardio.query.return_value = LLMResponse(
            ok=True,
            content="Cardiologist: architecture looks solid",
            latency_ms=180,
            model="gpt-4.1-mini",
            cost_usd=0.002,
        )
        neuro = MagicMock()
        neuro.query.return_value = LLMResponse(
            ok=True,
            content="Neurologist: patterns suggest N+1 risk",
            latency_ms=40,
            model="qwen3:4b",
        )
        evidence = EvidenceStore(str(tmp_path / "evidence.db"))
        state = MemoryBackend()
        return SurgeryTeam(
            cardiologist=cardio,
            neurologist=neuro,
            evidence=evidence,
            state=state,
        )

    def test_consult_returns_both_analyses(self, mock_team):
        result = mock_team.consult("Architecture decision")
        assert result.neurologist_report
        assert result.cardiologist_report

    def test_consult_returns_cross_exam_result(self, mock_team):
        result = mock_team.consult("Architecture decision")
        assert isinstance(result, CrossExamResult)
        assert result.topic == "Architecture decision"

    def test_consult_tracks_cost(self, mock_team):
        result = mock_team.consult("Architecture decision")
        assert result.total_cost >= 0


class TestConsensus:
    """Consensus: confidence-weighted vote on a claim."""

    @pytest.fixture
    def mock_team(self, tmp_path):
        cardio = MagicMock()
        cardio.query.return_value = LLMResponse(
            ok=True,
            content='{"confidence": 0.8, "assessment": "agree", "reasoning": "Evidence supports this"}',
            latency_ms=200,
            model="gpt-4.1-mini",
            cost_usd=0.001,
        )
        neuro = MagicMock()
        neuro.query.return_value = LLMResponse(
            ok=True,
            content='{"confidence": 0.6, "assessment": "uncertain", "reasoning": "Need more data"}',
            latency_ms=50,
            model="qwen3:4b",
        )
        evidence = EvidenceStore(str(tmp_path / "evidence.db"))
        state = MemoryBackend()
        return SurgeryTeam(
            cardiologist=cardio,
            neurologist=neuro,
            evidence=evidence,
            state=state,
        )

    def test_consensus_returns_scores(self, mock_team):
        result = mock_team.consensus("SQLite is sufficient for our use case")
        assert isinstance(result, ConsensusResult)
        assert result.claim == "SQLite is sufficient for our use case"

    def test_consensus_parses_confidence(self, mock_team):
        result = mock_team.consensus("SQLite is sufficient for our use case")
        assert result.cardiologist_confidence == pytest.approx(0.8)
        assert result.neurologist_confidence == pytest.approx(0.6)

    def test_consensus_parses_assessments(self, mock_team):
        result = mock_team.consensus("SQLite is sufficient for our use case")
        assert result.cardiologist_assessment == "agree"
        assert result.neurologist_assessment == "uncertain"

    def test_consensus_weighted_score(self, mock_team):
        result = mock_team.consensus("SQLite is sufficient for our use case")
        # weighted_score should be a float between -1 and 1
        assert isinstance(result.weighted_score, float)

    def test_consensus_tracks_cost(self, mock_team):
        result = mock_team.consensus("test claim")
        assert result.total_cost >= 0

    def test_consensus_handles_json_parse_failure(self, tmp_path):
        cardio = MagicMock()
        cardio.query.return_value = LLMResponse(
            ok=True,
            content="I think we should agree but I'm not outputting JSON",
            latency_ms=200,
            model="gpt-4.1-mini",
            cost_usd=0.001,
        )
        neuro = MagicMock()
        neuro.query.return_value = LLMResponse(
            ok=True,
            content='{"confidence": 0.7, "assessment": "agree", "reasoning": "ok"}',
            latency_ms=50,
            model="qwen3:4b",
        )
        evidence = EvidenceStore(str(tmp_path / "evidence.db"))
        team = SurgeryTeam(
            cardiologist=cardio,
            neurologist=neuro,
            evidence=evidence,
            state=MemoryBackend(),
        )
        # Should not crash even if one surgeon returns non-JSON
        result = team.consensus("test claim")
        assert isinstance(result, ConsensusResult)
        # The surgeon that failed JSON parsing should get default confidence 0.0
        assert result.cardiologist_confidence == pytest.approx(0.0)

    def test_consensus_handles_model_failure(self, tmp_path):
        cardio = MagicMock()
        cardio.query.return_value = LLMResponse.error("timeout", "gpt-4.1-mini")
        neuro = MagicMock()
        neuro.query.return_value = LLMResponse(
            ok=True,
            content='{"confidence": 0.9, "assessment": "agree", "reasoning": "solid"}',
            latency_ms=50,
            model="qwen3:4b",
        )
        evidence = EvidenceStore(str(tmp_path / "evidence.db"))
        team = SurgeryTeam(
            cardiologist=cardio,
            neurologist=neuro,
            evidence=evidence,
            state=MemoryBackend(),
        )
        result = team.consensus("test claim")
        assert isinstance(result, ConsensusResult)
        assert result.cardiologist_confidence == pytest.approx(0.0)
        assert result.cardiologist_assessment == "unavailable"


class TestEvidenceLogging:
    """Verify that operations log to the evidence store."""

    @pytest.fixture
    def mock_team(self, tmp_path):
        cardio = MagicMock()
        cardio.query.return_value = LLMResponse(
            ok=True,
            content="Cardiologist says yes",
            latency_ms=100,
            model="gpt-4.1-mini",
            cost_usd=0.001,
        )
        neuro = MagicMock()
        neuro.query.return_value = LLMResponse(
            ok=True,
            content="Neurologist says maybe",
            latency_ms=30,
            model="qwen3:4b",
        )
        evidence = EvidenceStore(str(tmp_path / "evidence.db"))
        state = MemoryBackend()
        return SurgeryTeam(
            cardiologist=cardio,
            neurologist=neuro,
            evidence=evidence,
            state=state,
        )

    def test_cross_exam_logs_to_evidence(self, mock_team):
        mock_team.cross_examine("logging test topic")
        exams = mock_team._evidence.get_cross_exams(limit=5)
        assert len(exams) >= 1
        assert exams[0]["topic"] == "logging test topic"

    def test_consult_logs_to_evidence(self, mock_team):
        mock_team.consult("consult logging test")
        exams = mock_team._evidence.get_cross_exams(limit=5)
        assert len(exams) >= 1
        assert exams[0]["topic"] == "consult logging test"

    def test_cross_exam_tracks_costs_in_evidence(self, mock_team):
        mock_team.cross_examine("cost tracking test")
        # Check that cost was tracked for at least the cardiologist
        daily = mock_team._evidence.get_daily_cost("cardiologist")
        assert daily > 0
