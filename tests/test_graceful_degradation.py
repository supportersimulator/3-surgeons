"""Graceful degradation tests for phased cross-examination.

Verifies that surgeon failures during each phase are handled properly:
- Remaining surgeon's findings still returned
- Appropriate warnings added
- Session state preserved across failures
"""
from __future__ import annotations

import pytest
from unittest.mock import MagicMock

from three_surgeons.core.cross_exam import SurgeryTeam
from three_surgeons.core.evidence import EvidenceStore
from three_surgeons.core.models import LLMResponse
from three_surgeons.core.sessions import LiveSession, SessionManager
from three_surgeons.core.state import MemoryBackend


# ── Helpers ──────────────────────────────────────────────────────────


def _ok_response(content: str, model: str = "test", cost: float = 0.001) -> LLMResponse:
    return LLMResponse(
        ok=True, content=content, latency_ms=100,
        model=model, cost_usd=cost,
    )


def _failing_provider() -> MagicMock:
    """Provider that returns error responses (simulates unreachable surgeon)."""
    p = MagicMock()
    p.query.return_value = LLMResponse.error("Connection refused", "unavailable")
    return p


def _ok_provider(content: str = "Analysis complete.", model: str = "test") -> MagicMock:
    p = MagicMock()
    p.query.return_value = _ok_response(content, model=model)
    return p


def _make_team(
    cardio: MagicMock,
    neuro: MagicMock,
    tmp_path,
) -> SurgeryTeam:
    evidence = EvidenceStore(str(tmp_path / "evidence.db"))
    return SurgeryTeam(
        cardiologist=cardio,
        neurologist=neuro,
        evidence=evidence,
        state=MemoryBackend(),
    )


def _make_session(tmp_path, topic: str = "test topic") -> LiveSession:
    sm = SessionManager(sessions_dir=tmp_path / "sessions")
    return sm.create(topic=topic, mode="iterative", depth="full", file_paths=[])


# ── 1. Cardiologist down during phase_start ──────────────────────────


class TestCardioDownPhaseStart:
    """When cardiologist is unreachable during phase_start, neurologist
    findings should still be returned with a warning."""

    def test_returns_neurologist_findings(self, tmp_path):
        team = _make_team(_failing_provider(), _ok_provider("Neuro analysis here"), tmp_path)
        session = _make_session(tmp_path)

        result = team.phase_start(session)

        assert result["neurologist"]["status"] == "ok"
        assert result["neurologist"]["findings"]
        assert "Neuro analysis here" in result["neurologist"]["findings"]

    def test_cardiologist_marked_unavailable(self, tmp_path):
        team = _make_team(_failing_provider(), _ok_provider("Neuro ok"), tmp_path)
        session = _make_session(tmp_path)

        result = team.phase_start(session)

        assert result["cardiologist"]["status"] == "unavailable"

    def test_warning_added(self, tmp_path):
        team = _make_team(_failing_provider(), _ok_provider("Neuro ok"), tmp_path)
        session = _make_session(tmp_path)

        result = team.phase_start(session)

        assert any("Cardiologist" in w and "unreachable" in w.lower() for w in result["warnings"])

    def test_session_phase_advanced(self, tmp_path):
        team = _make_team(_failing_provider(), _ok_provider("Neuro ok"), tmp_path)
        session = _make_session(tmp_path)

        team.phase_start(session)

        assert session.current_phase == "start"


# ── 2. Neurologist down during phase_start ───────────────────────────


class TestNeuroDownPhaseStart:
    """When neurologist is unreachable during phase_start, cardiologist
    findings should still be returned with a warning."""

    def test_returns_cardiologist_findings(self, tmp_path):
        team = _make_team(_ok_provider("Cardio analysis here"), _failing_provider(), tmp_path)
        session = _make_session(tmp_path)

        result = team.phase_start(session)

        assert result["cardiologist"]["status"] == "ok"
        assert "Cardio analysis here" in result["cardiologist"]["findings"]

    def test_neurologist_marked_unavailable(self, tmp_path):
        team = _make_team(_ok_provider("Cardio ok"), _failing_provider(), tmp_path)
        session = _make_session(tmp_path)

        result = team.phase_start(session)

        assert result["neurologist"]["status"] == "unavailable"

    def test_warning_added(self, tmp_path):
        team = _make_team(_ok_provider("Cardio ok"), _failing_provider(), tmp_path)
        session = _make_session(tmp_path)

        result = team.phase_start(session)

        assert any("Neurologist" in w and "unreachable" in w.lower() for w in result["warnings"])


# ── 3. Both surgeons down during phase_start ─────────────────────────


class TestBothDownPhaseStart:
    """When both surgeons are unreachable during phase_start, should
    return empty findings with appropriate warnings."""

    def test_both_marked_unavailable(self, tmp_path):
        team = _make_team(_failing_provider(), _failing_provider(), tmp_path)
        session = _make_session(tmp_path)

        result = team.phase_start(session)

        assert result["cardiologist"]["status"] == "unavailable"
        assert result["neurologist"]["status"] == "unavailable"

    def test_both_unreachable_warning(self, tmp_path):
        team = _make_team(_failing_provider(), _failing_provider(), tmp_path)
        session = _make_session(tmp_path)

        result = team.phase_start(session)

        assert any("Both" in w and "unreachable" in w.lower() for w in result["warnings"])

    def test_empty_findings(self, tmp_path):
        team = _make_team(_failing_provider(), _failing_provider(), tmp_path)
        session = _make_session(tmp_path)

        result = team.phase_start(session)

        assert result["cardiologist"]["findings"] == []
        assert result["neurologist"]["findings"] == []

    def test_phase_summary_indicates_failure(self, tmp_path):
        team = _make_team(_failing_provider(), _failing_provider(), tmp_path)
        session = _make_session(tmp_path)

        result = team.phase_start(session)

        assert "unavailable" in result["phase_summary"].lower()


# ── 4. One surgeon down during phase_deepen ──────────────────────────


class TestOneSurgeonDownPhaseDeepen:
    """When one surgeon fails during phase_deepen, the cross-review
    should proceed with the available surgeon."""

    def test_cardio_down_neuro_still_reviews(self, tmp_path):
        """Cardiologist fails during deepen, but neurologist can still
        review cardiologist's initial findings from phase_start."""
        cardio = _ok_provider("Cardio initial analysis")
        neuro = _ok_provider("Neuro initial analysis")
        team = _make_team(cardio, neuro, tmp_path)
        session = _make_session(tmp_path)

        # Run phase_start with both working
        team.phase_start(session)

        # Now cardiologist goes down for deepen
        cardio.query.return_value = LLMResponse.error("timeout", "gpt-4.1-mini")

        result = team.phase_deepen(session)

        # Neurologist should still have reviewed cardiologist's initial findings
        assert result["neurologist"]["status"] == "ok" or result["neurologist"]["findings"]
        assert result["phase"] == "deepen"

    def test_neuro_down_cardio_still_reviews(self, tmp_path):
        """Neurologist fails during deepen, but cardiologist can still
        review neurologist's initial findings from phase_start."""
        cardio = _ok_provider("Cardio initial analysis")
        neuro = _ok_provider("Neuro initial analysis")
        team = _make_team(cardio, neuro, tmp_path)
        session = _make_session(tmp_path)

        # Run phase_start with both working
        team.phase_start(session)

        # Now neurologist goes down for deepen
        neuro.query.return_value = LLMResponse.error("timeout", "qwen3:4b")

        result = team.phase_deepen(session)

        # Cardiologist should still have reviewed neurologist's initial findings
        assert result["cardiologist"]["status"] == "ok" or result["cardiologist"]["findings"]
        assert result["phase"] == "deepen"

    def test_deepen_session_advances(self, tmp_path):
        """Session phase advances to 'deepen' even with one surgeon down."""
        cardio = _ok_provider("Cardio initial")
        neuro = _ok_provider("Neuro initial")
        team = _make_team(cardio, neuro, tmp_path)
        session = _make_session(tmp_path)

        team.phase_start(session)
        cardio.query.return_value = LLMResponse.error("down", "gpt-4.1-mini")
        team.phase_deepen(session)

        assert session.current_phase == "deepen"


# ── 5. One surgeon down during phase_explore ─────────────────────────


class TestOneSurgeonDownPhaseExplore:
    """When one surgeon fails during exploration, the other should
    still contribute its unknown-unknowns analysis."""

    def test_cardio_down_neuro_explores(self, tmp_path):
        cardio = _ok_provider("Cardio analysis")
        neuro = _ok_provider("Neuro exploration: blind spots found")
        team = _make_team(cardio, neuro, tmp_path)
        session = _make_session(tmp_path)

        # Run through start and deepen
        team.phase_start(session)
        team.phase_deepen(session)

        # Cardiologist fails during explore
        cardio.query.return_value = LLMResponse.error("timeout", "gpt-4.1-mini")

        result = team.phase_explore(session)

        assert result["phase"] == "explore"
        assert result["neurologist"]["status"] == "ok"
        assert any("Cardiologist" in w for w in result["warnings"])

    def test_neuro_down_cardio_explores(self, tmp_path):
        cardio = _ok_provider("Cardio exploration: blind spots found")
        neuro = _ok_provider("Neuro analysis")
        team = _make_team(cardio, neuro, tmp_path)
        session = _make_session(tmp_path)

        team.phase_start(session)
        team.phase_deepen(session)

        # Neurologist fails during explore
        neuro.query.return_value = LLMResponse.error("timeout", "qwen3:4b")

        result = team.phase_explore(session)

        assert result["phase"] == "explore"
        assert result["cardiologist"]["status"] == "ok"
        assert any("Neurologist" in w for w in result["warnings"])

    def test_explore_warning_present(self, tmp_path):
        cardio = _ok_provider("Analysis")
        neuro = _ok_provider("Analysis")
        team = _make_team(cardio, neuro, tmp_path)
        session = _make_session(tmp_path)

        team.phase_start(session)
        team.phase_deepen(session)

        # Both fail during explore
        cardio.query.return_value = LLMResponse.error("down", "gpt-4.1-mini")
        neuro.query.return_value = LLMResponse.error("down", "qwen3:4b")

        result = team.phase_explore(session)

        assert any("Both" in w for w in result["warnings"])


# ── 6. Cardiologist down during phase_synthesize ─────────────────────


class TestCardioDownPhaseSynthesize:
    """When cardiologist fails during synthesis, the phase should still
    complete with a warning and consensus should be attempted."""

    def test_synthesis_fails_gracefully(self, tmp_path):
        cardio = _ok_provider("Analysis")
        neuro = _ok_provider("Analysis")
        team = _make_team(cardio, neuro, tmp_path)
        session = _make_session(tmp_path)

        # Run through all prior phases
        team.phase_start(session)
        team.phase_deepen(session)
        team.phase_explore(session)

        # Cardiologist goes down for synthesize
        cardio.query.return_value = LLMResponse.error("down", "gpt-4.1-mini")

        result = team.phase_synthesize(session)

        assert result["phase"] == "synthesize"
        assert any("Synthesis failed" in w or "unreachable" in w.lower() for w in result["warnings"])

    def test_consensus_still_attempted(self, tmp_path):
        cardio = _ok_provider("Analysis")
        neuro = _ok_provider("Analysis")
        team = _make_team(cardio, neuro, tmp_path)
        session = _make_session(tmp_path)

        team.phase_start(session)
        team.phase_deepen(session)
        team.phase_explore(session)

        # Cardiologist goes down
        cardio.query.return_value = LLMResponse.error("down", "gpt-4.1-mini")

        result = team.phase_synthesize(session)

        # Consensus score should be present (even if degraded)
        assert "consensus_score" in result

    def test_session_advances_to_synthesize(self, tmp_path):
        cardio = _ok_provider("Analysis")
        neuro = _ok_provider("Analysis")
        team = _make_team(cardio, neuro, tmp_path)
        session = _make_session(tmp_path)

        team.phase_start(session)
        team.phase_deepen(session)
        team.phase_explore(session)

        cardio.query.return_value = LLMResponse.error("down", "gpt-4.1-mini")
        team.phase_synthesize(session)

        assert session.current_phase == "synthesize"


# ── 7. Session state preserved after failure ─────────────────────────


class TestSessionStatePreservedAfterFailure:
    """Findings from the working surgeon should be accumulated in
    session state even when the other surgeon fails."""

    def test_findings_accumulated_from_working_surgeon(self, tmp_path):
        cardio = _failing_provider()
        neuro = _ok_provider("Neuro finding 1\nNeuro finding 2")
        team = _make_team(cardio, neuro, tmp_path)
        session = _make_session(tmp_path)

        team.phase_start(session)

        # Session should have accumulated neurologist findings
        assert len(session.accumulated_findings) >= 1
        last = session.accumulated_findings[-1]
        assert last["neurologist"] is not None
        assert len(last["neurologist"]) > 0

    def test_warnings_accumulated_in_session(self, tmp_path):
        cardio = _failing_provider()
        neuro = _ok_provider("Neuro ok")
        team = _make_team(cardio, neuro, tmp_path)
        session = _make_session(tmp_path)

        team.phase_start(session)

        assert len(session.warnings) > 0
        assert any("Cardiologist" in w for w in session.warnings)

    def test_cost_tracked_for_working_surgeon_only(self, tmp_path):
        cardio = _failing_provider()
        neuro = _ok_provider("Neuro ok")
        team = _make_team(cardio, neuro, tmp_path)
        session = _make_session(tmp_path)

        team.phase_start(session)

        # Cost should reflect only the neurologist's cost
        assert session.total_cost > 0

    def test_multi_phase_degradation_preserves_all_findings(self, tmp_path):
        """Run start + deepen with cardiologist down the whole time.
        All neurologist findings from both phases should be in session."""
        cardio = _failing_provider()
        neuro = _ok_provider("Neurologist analysis")
        team = _make_team(cardio, neuro, tmp_path)
        session = _make_session(tmp_path)

        team.phase_start(session)
        team.phase_deepen(session)

        # Should have findings from both phases
        phases_recorded = [f["phase"] for f in session.accumulated_findings]
        assert "start" in phases_recorded
        assert "deepen" in phases_recorded

    def test_session_persists_across_phases_with_failure(self, tmp_path):
        """Verify session can be saved/loaded between phases even with failures."""
        sm = SessionManager(sessions_dir=tmp_path / "sessions")
        session = sm.create(topic="persistence test", mode="iterative", depth="full")

        cardio = _failing_provider()
        neuro = _ok_provider("Neuro finding")
        team = _make_team(cardio, neuro, tmp_path)

        team.phase_start(session)
        sm.save(session)

        # Reload session
        loaded = sm.get(session.session_id)
        assert loaded is not None
        assert loaded.current_phase == "start"
        assert len(loaded.accumulated_findings) >= 1
        assert len(loaded.warnings) > 0

    def test_exception_raising_provider_handled(self, tmp_path):
        """Provider that raises an exception (not just error response)
        should be caught by _safe_query and treated as unavailable."""
        cardio = MagicMock()
        cardio.query.side_effect = ConnectionError("Network unreachable")
        neuro = _ok_provider("Neuro ok")
        team = _make_team(cardio, neuro, tmp_path)
        session = _make_session(tmp_path)

        result = team.phase_start(session)

        assert result["cardiologist"]["status"] == "unavailable"
        assert result["neurologist"]["status"] == "ok"
        assert any("Cardiologist" in w for w in result["warnings"])
