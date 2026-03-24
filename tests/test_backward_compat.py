"""Backward compatibility tests for the Live Surgery phased methods.

Ensures that the OLD cross_examine(), cross_examine_iterative(), and MCP
cross_examine tool continue to work identically after adding the phased
methods (phase_start, phase_deepen, phase_explore, phase_synthesize).

Uses the same FakeLLMProvider/mock patterns from existing tests.
"""
from __future__ import annotations

import inspect
from unittest.mock import MagicMock, patch

import pytest

from three_surgeons.core.cross_exam import (
    ConsensusResult,
    CrossExamResult,
    ReviewMode,
    SurgeryTeam,
)
from three_surgeons.core.evidence import EvidenceStore
from three_surgeons.core.models import LLMResponse
from three_surgeons.core.state import MemoryBackend


# ── Helpers ──────────────────────────────────────────────────────────────


def _make_team(tmp_path):
    """Build a SurgeryTeam with mock LLM providers (old 4-arg signature)."""
    cardio = MagicMock()
    cardio.query.return_value = LLMResponse(
        ok=True,
        content="Cardiologist: backward compat analysis",
        latency_ms=150,
        model="gpt-4.1-mini",
        cost_usd=0.001,
    )
    neuro = MagicMock()
    neuro.query.return_value = LLMResponse(
        ok=True,
        content="Neurologist: backward compat analysis",
        latency_ms=40,
        model="qwen3:4b",
    )
    evidence = EvidenceStore(str(tmp_path / "compat_evidence.db"))
    state = MemoryBackend()
    return SurgeryTeam(
        cardiologist=cardio,
        neurologist=neuro,
        evidence=evidence,
        state=state,
    )


# ── 1. Old cross_examine() still works ──────────────────────────────────


class TestOldCrossExamineUnchanged:
    """cross_examine() returns CrossExamResult with expected fields."""

    @pytest.fixture
    def team(self, tmp_path):
        return _make_team(tmp_path)

    def test_returns_cross_exam_result(self, team):
        result = team.cross_examine("backward compat topic")
        assert isinstance(result, CrossExamResult)

    def test_has_cardiologist_report(self, team):
        result = team.cross_examine("backward compat topic")
        assert result.cardiologist_report is not None

    def test_has_neurologist_report(self, team):
        result = team.cross_examine("backward compat topic")
        assert result.neurologist_report is not None

    def test_has_synthesis(self, team):
        result = team.cross_examine("backward compat topic")
        # Synthesis may be None if model returns non-ideal content,
        # but the field must exist on the result.
        assert hasattr(result, "synthesis")

    def test_has_exploration_fields(self, team):
        result = team.cross_examine("backward compat topic")
        assert hasattr(result, "cardiologist_exploration")
        assert hasattr(result, "neurologist_exploration")

    def test_total_cost_non_negative(self, team):
        result = team.cross_examine("backward compat topic")
        assert result.total_cost >= 0

    def test_total_latency_positive(self, team):
        result = team.cross_examine("backward compat topic")
        assert result.total_latency_ms > 0

    def test_topic_preserved(self, team):
        result = team.cross_examine("specific topic string")
        assert result.topic == "specific topic string"

    def test_signature_unchanged(self):
        """cross_examine must still accept (topic, depth, file_paths)."""
        sig = inspect.signature(SurgeryTeam.cross_examine)
        params = list(sig.parameters.keys())
        assert "self" in params
        assert "topic" in params
        assert "depth" in params
        assert "file_paths" in params


# ── 2. Old cross_examine_iterative() still works ────────────────────────


class TestOldCrossExamineIterativeUnchanged:
    """cross_examine_iterative() runs multiple iterations, returns CrossExamResult."""

    @pytest.fixture
    def team(self, tmp_path):
        return _make_team(tmp_path)

    def test_single_mode_returns_result(self, team):
        result = team.cross_examine_iterative("compat topic", mode=ReviewMode.SINGLE)
        assert isinstance(result, CrossExamResult)
        assert result.iteration_count == 1
        assert result.mode_used == "single"

    def test_iterative_mode_returns_result(self, team):
        """Iterative mode with high consensus exits early."""
        team.consensus = MagicMock(return_value=ConsensusResult(
            claim="addressed",
            cardiologist_confidence=0.9,
            cardiologist_assessment="agree",
            neurologist_confidence=0.85,
            neurologist_assessment="agree",
            weighted_score=0.88,
        ))
        result = team.cross_examine_iterative("compat topic", mode=ReviewMode.ITERATIVE)
        assert isinstance(result, CrossExamResult)
        assert result.iteration_count <= 3

    def test_iterative_caps_at_max(self, team):
        """Low consensus causes max iterations and escalation."""
        team.consensus = MagicMock(return_value=ConsensusResult(
            claim="not resolved",
            cardiologist_confidence=0.3,
            cardiologist_assessment="disagree",
            neurologist_confidence=0.2,
            neurologist_assessment="uncertain",
            weighted_score=-0.4,
        ))
        result = team.cross_examine_iterative("compat topic", mode=ReviewMode.ITERATIVE)
        assert result.iteration_count == 3
        assert result.escalation_needed is True
        assert result.unresolved_summary is not None

    def test_signature_unchanged(self):
        """cross_examine_iterative must still accept (topic, mode, consensus_threshold, depth, file_paths)."""
        sig = inspect.signature(SurgeryTeam.cross_examine_iterative)
        params = list(sig.parameters.keys())
        assert "self" in params
        assert "topic" in params
        assert "mode" in params
        assert "consensus_threshold" in params
        assert "depth" in params
        assert "file_paths" in params

    def test_default_mode_is_single(self):
        sig = inspect.signature(SurgeryTeam.cross_examine_iterative)
        assert sig.parameters["mode"].default == ReviewMode.SINGLE


# ── 3. Old MCP tool cross_examine unchanged ─────────────────────────────


class TestOldMCPCrossExamineUnchanged:
    """_cross_examine() MCP tool returns same dict format as before."""

    def test_returns_dict_with_expected_keys(self):
        from three_surgeons.mcp.server import _cross_examine

        with patch("three_surgeons.mcp.server._build_surgery_team") as mock_team_fn:
            mock_result = MagicMock(
                topic="mcp topic",
                cardiologist_report="cardio report",
                neurologist_report="neuro report",
                cardiologist_exploration="cardio explore",
                neurologist_exploration="neuro explore",
                synthesis="combined synthesis",
                total_cost=0.02,
                total_latency_ms=800,
                iteration_count=1,
                mode_used="single",
                escalation_needed=False,
                unresolved_summary=None,
            )
            mock_team_fn.return_value.cross_examine_iterative.return_value = mock_result

            result = _cross_examine("mcp topic")

        assert isinstance(result, dict)
        expected_keys = {
            "topic", "cardiologist_report", "neurologist_report",
            "cardiologist_exploration", "neurologist_exploration",
            "synthesis", "total_cost", "total_latency_ms",
            "iteration_count", "mode_used", "escalation_needed",
            "unresolved_summary",
        }
        assert expected_keys.issubset(set(result.keys()))

    def test_signature_has_topic_depth_mode_file_paths(self):
        from three_surgeons.mcp.server import _cross_examine

        sig = inspect.signature(_cross_examine)
        params = list(sig.parameters.keys())
        assert "topic" in params
        assert "depth" in params
        assert "mode" in params
        assert "file_paths" in params

    def test_default_mode_is_single(self):
        from three_surgeons.mcp.server import _cross_examine

        sig = inspect.signature(_cross_examine)
        assert sig.parameters["mode"].default == "single"

    def test_delegates_to_cross_examine_iterative(self):
        """MCP tool must delegate to cross_examine_iterative, not cross_examine directly."""
        from three_surgeons.mcp.server import _cross_examine

        with patch("three_surgeons.mcp.server._build_surgery_team") as mock_team_fn:
            mock_result = MagicMock(
                topic="t", cardiologist_report="c", neurologist_report="n",
                cardiologist_exploration="ec", neurologist_exploration="en",
                synthesis="s", total_cost=0.0, total_latency_ms=0,
                iteration_count=1, mode_used="single",
                escalation_needed=False, unresolved_summary=None,
            )
            mock_team_fn.return_value.cross_examine_iterative.return_value = mock_result

            _cross_examine("t")

            mock_team_fn.return_value.cross_examine_iterative.assert_called_once()


# ── 4. TOOL_NAMES includes both old and new tools ───────────────────────


class TestToolNamesBackwardCompat:
    """Old tools must not be removed from TOOL_NAMES when new ones are added."""

    def test_old_tools_still_present(self):
        from three_surgeons.mcp.server import TOOL_NAMES

        old_tools = {
            "probe", "cross_examine", "consult", "consensus",
            "sentinel_run", "gains_gate",
            "ab_propose", "ab_start", "ab_measure", "ab_conclude",
            "neurologist_pulse_tool", "neurologist_challenge_tool",
            "introspect_tool", "ask_local_tool", "ask_remote_tool",
            "cardio_review_tool", "ab_validate_tool", "research_tool",
        }
        tool_set = set(TOOL_NAMES)
        missing = old_tools - tool_set
        assert not missing, f"Old tools removed from TOOL_NAMES: {missing}"

    def test_new_phased_tools_present(self):
        from three_surgeons.mcp.server import TOOL_NAMES

        new_tools = {
            "cross_examine_start",
            "cross_examine_deepen",
            "cross_examine_explore",
            "cross_examine_synthesize",
            "cross_examine_iterate",
        }
        tool_set = set(TOOL_NAMES)
        missing = new_tools - tool_set
        assert not missing, f"New phased tools missing from TOOL_NAMES: {missing}"

    def test_old_cross_examine_not_replaced(self):
        """cross_examine (old) must coexist with cross_examine_start (new)."""
        from three_surgeons.mcp.server import TOOL_NAMES

        assert "cross_examine" in TOOL_NAMES
        assert "cross_examine_start" in TOOL_NAMES


# ── 5. LiveSession addition doesn't break SurgeryTeam construction ──────


class TestSurgeryTeamConstructionUnchanged:
    """SurgeryTeam.__init__ signature must remain unchanged."""

    def test_init_signature(self):
        sig = inspect.signature(SurgeryTeam.__init__)
        params = list(sig.parameters.keys())
        # adapter param added in v1.1 — optional, defaults to StandaloneAdapter
        assert params == ["self", "cardiologist", "neurologist", "evidence", "state", "adapter"]

    def test_construction_with_mocks(self, tmp_path):
        """Old 4-arg construction pattern still works."""
        team = _make_team(tmp_path)
        assert team is not None
        assert hasattr(team, "cross_examine")
        assert hasattr(team, "cross_examine_iterative")
        assert hasattr(team, "consult")
        assert hasattr(team, "consensus")

    def test_phased_methods_also_exist(self, tmp_path):
        """New phased methods exist alongside old ones."""
        team = _make_team(tmp_path)
        assert hasattr(team, "phase_start")
        assert hasattr(team, "phase_deepen")
        assert hasattr(team, "phase_explore")
        assert hasattr(team, "phase_synthesize")

    def test_old_methods_callable_after_phased_addition(self, tmp_path):
        """Old methods still callable — phased additions are additive."""
        team = _make_team(tmp_path)
        # cross_examine
        result = team.cross_examine("construction compat test")
        assert isinstance(result, CrossExamResult)
        # consult
        result2 = team.consult("construction compat consult")
        assert isinstance(result2, CrossExamResult)


# ── 6. sessions.py import is additive ───────────────────────────────────


class TestSessionsImportAdditive:
    """Importing sessions module must not affect cross_exam module."""

    def test_sessions_importable(self):
        from three_surgeons.core import sessions
        assert hasattr(sessions, "LiveSession")
        assert hasattr(sessions, "SessionManager")

    def test_cross_exam_importable_independently(self):
        """cross_exam module works regardless of sessions import."""
        from three_surgeons.core.cross_exam import (
            CrossExamResult,
            ReviewMode,
            SurgeryTeam,
        )
        assert CrossExamResult is not None
        assert ReviewMode is not None
        assert SurgeryTeam is not None

    def test_cross_exam_imports_sessions_without_error(self):
        """cross_exam.py imports LiveSession at module level — verify no circular import."""
        # If this import succeeds, the dependency is clean
        from three_surgeons.core.cross_exam import SurgeryTeam
        from three_surgeons.core.sessions import LiveSession
        assert SurgeryTeam is not None
        assert LiveSession is not None

    def test_sessions_import_does_not_alter_cross_exam_result(self, tmp_path):
        """CrossExamResult fields unchanged after sessions import."""
        from three_surgeons.core.sessions import LiveSession  # noqa: F401

        result = CrossExamResult(topic="additive test")
        assert result.topic == "additive test"
        assert result.iteration_count == 1
        assert result.mode_used == "single"
        assert result.escalation_needed is False
