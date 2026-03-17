"""Tests for phased cross-examination methods on SurgeryTeam.

Validates the 5 Live Surgery Transparency phases:
phase_start, phase_deepen, phase_explore, phase_synthesize, phase_iterate.
"""
from __future__ import annotations

import json
from unittest.mock import MagicMock

import pytest

from three_surgeons.core.cross_exam import SurgeryTeam
from three_surgeons.core.evidence import EvidenceStore
from three_surgeons.core.models import LLMResponse
from three_surgeons.core.sessions import LiveSession
from three_surgeons.core.state import MemoryBackend


def _make_session(topic: str = "Should we use Redis or Postgres?", mode: str = "iterative") -> LiveSession:
    return LiveSession(
        session_id="test-session-001",
        topic=topic,
        mode=mode,
        depth="full",
    )


def _ok_response(content: str, model: str = "gpt-4.1-mini", cost: float = 0.005, latency: int = 1200) -> LLMResponse:
    return LLMResponse(ok=True, content=content, latency_ms=latency, model=model, cost_usd=cost)


def _make_team(tmp_path, cardio_resp=None, neuro_resp=None):
    """Build a SurgeryTeam with mocked providers."""
    cardio = MagicMock()
    if cardio_resp is not None:
        cardio.query.return_value = cardio_resp
    else:
        cardio.query.return_value = _ok_response(
            "Cardiologist: Redis is faster for caching but Postgres for durability.",
            cost=0.005,
            latency=1200,
        )

    neuro = MagicMock()
    if neuro_resp is not None:
        neuro.query.return_value = neuro_resp
    else:
        neuro.query.return_value = _ok_response(
            "Neurologist: Postgres handles complex queries better.",
            model="qwen3:4b",
            cost=0.0,
            latency=3400,
        )

    evidence = EvidenceStore(str(tmp_path / "evidence.db"))
    state = MemoryBackend()
    return SurgeryTeam(cardiologist=cardio, neurologist=neuro, evidence=evidence, state=state)


class TestPhaseStart:
    """Phase 1: Independent analysis by both surgeons."""

    def test_returns_structured_result(self, tmp_path):
        team = _make_team(tmp_path)
        session = _make_session()
        result = team.phase_start(session)

        assert result["session_id"] == "test-session-001"
        assert result["phase"] == "start"
        assert result["iteration"] == 1
        assert result["next_action"] == "deepen"
        assert result["cardiologist"]["status"] == "ok"
        assert result["neurologist"]["status"] == "ok"
        assert len(result["cardiologist"]["findings"]) > 0
        assert len(result["neurologist"]["findings"]) > 0

    def test_advances_session_phase(self, tmp_path):
        team = _make_team(tmp_path)
        session = _make_session()
        team.phase_start(session)
        assert session.current_phase == "start"

    def test_tracks_cost_on_session(self, tmp_path):
        team = _make_team(tmp_path)
        session = _make_session()
        team.phase_start(session)
        assert session.total_cost > 0

    def test_adds_findings_to_session(self, tmp_path):
        team = _make_team(tmp_path)
        session = _make_session()
        team.phase_start(session)
        assert len(session.accumulated_findings) == 1
        f = session.accumulated_findings[0]
        assert f["phase"] == "start"
        assert f["iteration"] == 1

    def test_graceful_degradation_cardio_fails(self, tmp_path):
        team = _make_team(
            tmp_path,
            cardio_resp=LLMResponse.error("API timeout", "gpt-4.1-mini"),
        )
        session = _make_session()
        result = team.phase_start(session)

        assert result["cardiologist"]["status"] == "unavailable"
        assert result["neurologist"]["status"] == "ok"
        assert any("Cardiologist" in w for w in result["warnings"])

    def test_graceful_degradation_neuro_fails(self, tmp_path):
        team = _make_team(
            tmp_path,
            neuro_resp=LLMResponse.error("timeout", "qwen3:4b"),
        )
        session = _make_session()
        result = team.phase_start(session)

        assert result["neurologist"]["status"] == "unavailable"
        assert result["cardiologist"]["status"] == "ok"
        assert any("Neurologist" in w for w in result["warnings"])

    def test_both_fail_returns_error(self, tmp_path):
        team = _make_team(
            tmp_path,
            cardio_resp=LLMResponse.error("fail", "gpt-4.1-mini"),
            neuro_resp=LLMResponse.error("fail", "qwen3:4b"),
        )
        session = _make_session()
        result = team.phase_start(session)

        assert result["cardiologist"]["status"] == "unavailable"
        assert result["neurologist"]["status"] == "unavailable"
        assert any("Both" in w for w in result["warnings"])


class TestPhaseDeepen:
    """Phase 2: Cross-review of each other's analysis."""

    def test_sends_cross_review_prompts(self, tmp_path):
        team = _make_team(tmp_path)
        session = _make_session()

        # Run phase_start first to populate findings
        team.phase_start(session)
        result = team.phase_deepen(session)

        assert result["phase"] == "deepen"
        assert result["next_action"] == "explore"
        assert session.current_phase == "deepen"

    def test_adds_findings(self, tmp_path):
        team = _make_team(tmp_path)
        session = _make_session()
        team.phase_start(session)
        team.phase_deepen(session)

        deepen_findings = [f for f in session.accumulated_findings if f["phase"] == "deepen"]
        assert len(deepen_findings) == 1

    def test_no_prior_findings_warns(self, tmp_path):
        team = _make_team(tmp_path)
        session = _make_session()
        # Skip phase_start — advance manually
        session.advance_phase("start")
        result = team.phase_deepen(session)

        # Should warn about missing findings
        assert any("findings" in w.lower() for w in result["warnings"])


class TestPhaseExplore:
    """Phase 3: Open exploration — unknown unknowns."""

    def test_sends_exploration_prompts(self, tmp_path):
        team = _make_team(tmp_path)
        session = _make_session()
        team.phase_start(session)
        team.phase_deepen(session)
        result = team.phase_explore(session)

        assert result["phase"] == "explore"
        assert result["next_action"] == "synthesize"
        assert session.current_phase == "explore"

    def test_both_surgeons_queried(self, tmp_path):
        team = _make_team(tmp_path)
        session = _make_session()
        team.phase_start(session)
        team.phase_deepen(session)
        result = team.phase_explore(session)

        assert result["cardiologist"]["status"] == "ok"
        assert result["neurologist"]["status"] == "ok"

    def test_adds_explore_findings(self, tmp_path):
        team = _make_team(tmp_path)
        session = _make_session()
        team.phase_start(session)
        team.phase_deepen(session)
        team.phase_explore(session)

        explore_findings = [f for f in session.accumulated_findings if f["phase"] == "explore"]
        assert len(explore_findings) == 1

    def test_single_surgeon_failure_continues(self, tmp_path):
        """If one surgeon fails exploration, the other still contributes."""
        cardio = MagicMock()
        cardio.query.return_value = _ok_response("Cardio insight", cost=0.005)
        neuro = MagicMock()
        # Neuro fails on third call (explore), succeeds on first two
        neuro.query.side_effect = [
            _ok_response("Neuro initial", model="qwen3:4b", cost=0.0, latency=100),
            _ok_response("Neuro review", model="qwen3:4b", cost=0.0, latency=100),
            LLMResponse.error("timeout", "qwen3:4b"),
        ]
        evidence = EvidenceStore(str(tmp_path / "evidence.db"))
        team = SurgeryTeam(cardiologist=cardio, neurologist=neuro, evidence=evidence, state=MemoryBackend())

        session = _make_session()
        team.phase_start(session)
        team.phase_deepen(session)
        result = team.phase_explore(session)

        assert result["cardiologist"]["status"] == "ok"
        assert result["neurologist"]["status"] == "unavailable"
        assert any("Neurologist" in w for w in result["warnings"])


class TestPhaseSynthesize:
    """Phase 4: Synthesis + consensus scoring."""

    def _run_through_explore(self, tmp_path):
        """Helper: run phases 1-3, return (team, session)."""
        # Use a consensus-compatible response for the synthesis phase
        cardio = MagicMock()
        cardio.query.return_value = _ok_response("Synthesis complete.", cost=0.005)
        neuro = MagicMock()
        neuro.query.return_value = _ok_response("Neuro analysis.", model="qwen3:4b", cost=0.0, latency=100)

        evidence = EvidenceStore(str(tmp_path / "evidence.db"))
        team = SurgeryTeam(cardiologist=cardio, neurologist=neuro, evidence=evidence, state=MemoryBackend())

        session = _make_session()
        team.phase_start(session)
        team.phase_deepen(session)
        team.phase_explore(session)
        return team, session

    def test_calculates_consensus_score(self, tmp_path):
        team, session = self._run_through_explore(tmp_path)

        # Override to return consensus JSON for the consensus call
        cardio_mock = team._cardiologist
        neuro_mock = team._neurologist
        # Synthesis call returns text, consensus calls return JSON
        cardio_mock.query.side_effect = [
            _ok_response("Key finding: Redis wins for caching.", cost=0.005),
            _ok_response(json.dumps({"confidence": 0.8, "assessment": "agree"}), cost=0.001),
        ]
        neuro_mock.query.return_value = _ok_response(
            json.dumps({"confidence": 0.7, "assessment": "agree"}),
            model="qwen3:4b", cost=0.0,
        )

        result = team.phase_synthesize(session)

        assert result["phase"] == "synthesize"
        assert "consensus_score" in result
        assert result["consensus_score"] > 0
        assert len(session.consensus_scores) == 1

    def test_next_action_based_on_consensus(self, tmp_path):
        team, session = self._run_through_explore(tmp_path)

        # High consensus → done
        cardio_mock = team._cardiologist
        neuro_mock = team._neurologist
        cardio_mock.query.side_effect = [
            _ok_response("Synthesis.", cost=0.005),
            _ok_response(json.dumps({"confidence": 0.9, "assessment": "agree"}), cost=0.001),
        ]
        neuro_mock.query.return_value = _ok_response(
            json.dumps({"confidence": 0.9, "assessment": "agree"}),
            model="qwen3:4b", cost=0.0,
        )

        result = team.phase_synthesize(session)
        assert result["next_action"] == "done"

    def test_low_consensus_suggests_iterate(self, tmp_path):
        team, session = self._run_through_explore(tmp_path)

        # Low consensus → iterate
        cardio_mock = team._cardiologist
        neuro_mock = team._neurologist
        cardio_mock.query.side_effect = [
            _ok_response("Synthesis.", cost=0.005),
            _ok_response(json.dumps({"confidence": 0.3, "assessment": "disagree"}), cost=0.001),
        ]
        neuro_mock.query.return_value = _ok_response(
            json.dumps({"confidence": 0.2, "assessment": "uncertain"}),
            model="qwen3:4b", cost=0.0,
        )

        result = team.phase_synthesize(session)
        # With low consensus and iteration < max, should suggest iterate
        assert result["next_action"] == "iterate"


class TestPhaseIterate:
    """Phase 5: Increment iteration and reset."""

    def test_increments_iteration(self, tmp_path):
        team = _make_team(tmp_path)
        session = _make_session()
        team.phase_start(session)
        assert session.current_iteration == 1

        # Manually advance through phases for iterate
        team.phase_deepen(session)
        team.phase_explore(session)
        session.advance_phase("synthesize")

        result = team.phase_iterate(session)

        assert session.current_iteration == 2
        assert result["iteration"] == 2
        assert result["phase"] == "start"
        assert result["next_action"] == "start"

    def test_enriches_topic_with_prior_findings(self, tmp_path):
        team = _make_team(tmp_path)
        session = _make_session()
        original_topic = session.topic

        team.phase_start(session)
        team.phase_deepen(session)
        team.phase_explore(session)
        session.advance_phase("synthesize")

        team.phase_iterate(session)

        # Topic should now include prior findings
        assert "Prior findings" in session.topic
        assert original_topic in session.topic

    def test_resets_phase_to_start(self, tmp_path):
        team = _make_team(tmp_path)
        session = _make_session()
        team.phase_start(session)
        team.phase_deepen(session)
        team.phase_explore(session)
        session.advance_phase("synthesize")

        team.phase_iterate(session)
        assert session.current_phase == "start"

    def test_surgeon_status_pending(self, tmp_path):
        team = _make_team(tmp_path)
        session = _make_session()
        team.phase_start(session)
        team.phase_deepen(session)
        team.phase_explore(session)
        session.advance_phase("synthesize")

        result = team.phase_iterate(session)
        assert result["cardiologist"]["status"] == "pending"
        assert result["neurologist"]["status"] == "pending"


class TestPhaseSequenceIntegration:
    """Full phase sequence: start -> deepen -> explore -> synthesize -> iterate."""

    def test_full_sequence(self, tmp_path):
        """Run all 5 phases and verify state transitions."""
        cardio = MagicMock()
        neuro = MagicMock()

        # Build response sequence: start, deepen, explore, synth, consensus(cardio), consensus(neuro)
        cardio.query.side_effect = [
            _ok_response("Cardio initial analysis.", cost=0.005),
            _ok_response("Cardio cross-review.", cost=0.005),
            _ok_response("Cardio blind spots.", cost=0.005),
            _ok_response("Cardio synthesis.", cost=0.005),
            _ok_response(json.dumps({"confidence": 0.4, "assessment": "uncertain"}), cost=0.001),
        ]
        neuro.query.side_effect = [
            _ok_response("Neuro initial.", model="qwen3:4b", cost=0.0, latency=100),
            _ok_response("Neuro cross-review.", model="qwen3:4b", cost=0.0, latency=100),
            _ok_response("Neuro blind spots.", model="qwen3:4b", cost=0.0, latency=100),
            _ok_response(json.dumps({"confidence": 0.3, "assessment": "uncertain"}), model="qwen3:4b", cost=0.0, latency=100),
        ]

        evidence = EvidenceStore(str(tmp_path / "evidence.db"))
        team = SurgeryTeam(cardiologist=cardio, neurologist=neuro, evidence=evidence, state=MemoryBackend())
        session = _make_session()

        r1 = team.phase_start(session)
        assert r1["phase"] == "start"
        assert r1["next_action"] == "deepen"

        r2 = team.phase_deepen(session)
        assert r2["phase"] == "deepen"
        assert r2["next_action"] == "explore"

        r3 = team.phase_explore(session)
        assert r3["phase"] == "explore"
        assert r3["next_action"] == "synthesize"

        r4 = team.phase_synthesize(session)
        assert r4["phase"] == "synthesize"
        # Low consensus + iteration < max → iterate
        assert r4["next_action"] == "iterate"

        r5 = team.phase_iterate(session)
        assert r5["phase"] == "start"
        assert r5["iteration"] == 2

        # Accumulated findings should have entries from all phases
        assert len(session.accumulated_findings) >= 4  # start, deepen, explore, synthesize
        assert len(session.consensus_scores) == 1
        assert session.total_cost > 0

    def test_phase_start_after_iterate_no_crash(self, tmp_path):
        """Regression: CLI calls phase_iterate then phase_start on iteration > 1.

        phase_iterate sets phase to 'start', then phase_start must not crash
        trying start→start transition (was ValueError before fix).
        """
        team = _make_team(tmp_path)
        session = _make_session()

        # Run full first iteration
        team.phase_start(session)
        team.phase_deepen(session)
        team.phase_explore(session)
        team.phase_synthesize(session)

        # Iterate resets to start
        team.phase_iterate(session)
        assert session.current_phase == "start"

        # This is the exact call sequence from CLI --live on iteration > 1.
        # Before the fix, this raised ValueError: Cannot transition start→start
        result = team.phase_start(session)
        assert result["phase"] == "start"
        assert session.current_iteration == 2
