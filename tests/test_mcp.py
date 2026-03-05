"""Tests for the MCP server module.

Validates:
- Module is importable (even without mcp SDK installed)
- All expected tools are registered via TOOL_NAMES
- plugin.json declares the MCP server
- Tool functions exist and have correct signatures
- Tools delegate to core/ (no business logic in server)
"""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


class TestMCPServerImport:
    """Module importability and basic structure."""

    def test_server_module_importable(self):
        """The MCP server module should be importable even without mcp SDK."""
        from three_surgeons.mcp import server

        assert hasattr(server, "TOOL_NAMES")

    def test_tools_registered(self):
        """All expected tools should be listed in TOOL_NAMES."""
        from three_surgeons.mcp.server import TOOL_NAMES

        expected = {
            "probe",
            "cross_examine",
            "consult",
            "consensus",
            "sentinel_run",
            "gains_gate",
            "ab_propose",
            "ab_start",
            "ab_measure",
            "ab_conclude",
            "neurologist_pulse_tool",
            "neurologist_challenge_tool",
            "introspect_tool",
            "ask_local_tool",
            "ask_remote_tool",
            "cardio_review_tool",
            "ab_validate_tool",
            "research_tool",
        }
        assert expected.issubset(set(TOOL_NAMES))

    def test_tool_names_is_list_or_tuple(self):
        """TOOL_NAMES should be a sequence type."""
        from three_surgeons.mcp.server import TOOL_NAMES

        assert isinstance(TOOL_NAMES, (list, tuple))

    def test_no_extra_unknown_tools(self):
        """TOOL_NAMES should only contain known tools."""
        from three_surgeons.mcp.server import TOOL_NAMES

        known = {
            "probe",
            "cross_examine",
            "consult",
            "consensus",
            "sentinel_run",
            "gains_gate",
            "ab_propose",
            "ab_start",
            "ab_measure",
            "ab_conclude",
            "neurologist_pulse_tool",
            "neurologist_challenge_tool",
            "introspect_tool",
            "ask_local_tool",
            "ask_remote_tool",
            "cardio_review_tool",
            "ab_validate_tool",
            "research_tool",
        }
        for name in TOOL_NAMES:
            assert name in known, f"Unexpected tool: {name}"


class TestPluginJSON:
    """plugin.json MCP server declaration."""

    def test_plugin_json_has_mcp_servers(self):
        """plugin.json should declare the MCP server."""
        plugin_json = Path(__file__).parent.parent / ".claude-plugin" / "plugin.json"
        data = json.loads(plugin_json.read_text())
        assert "mcpServers" in data
        assert "3-surgeons" in data["mcpServers"]

    def test_plugin_json_mcp_server_command(self):
        """MCP server should use python -m invocation."""
        plugin_json = Path(__file__).parent.parent / ".claude-plugin" / "plugin.json"
        data = json.loads(plugin_json.read_text())
        server_cfg = data["mcpServers"]["3-surgeons"]
        assert server_cfg["command"] == "python"
        assert "-m" in server_cfg["args"]
        assert "three_surgeons.mcp.server" in server_cfg["args"]


class TestToolFunctions:
    """Each tool function exists, has correct signature, and delegates to core/."""

    def test_probe_function_exists(self):
        """probe() should exist and be callable."""
        from three_surgeons.mcp.server import _probe

        assert callable(_probe)

    def test_cross_examine_function_exists(self):
        """cross_examine() should exist and be callable."""
        from three_surgeons.mcp.server import _cross_examine

        assert callable(_cross_examine)

    def test_consult_function_exists(self):
        """consult() should exist and be callable."""
        from three_surgeons.mcp.server import _consult

        assert callable(_consult)

    def test_consensus_function_exists(self):
        """consensus() should exist and be callable."""
        from three_surgeons.mcp.server import _consensus

        assert callable(_consensus)

    def test_sentinel_run_function_exists(self):
        """sentinel_run() should exist and be callable."""
        from three_surgeons.mcp.server import _sentinel_run

        assert callable(_sentinel_run)

    def test_gains_gate_function_exists(self):
        """gains_gate() should exist and be callable."""
        from three_surgeons.mcp.server import _gains_gate

        assert callable(_gains_gate)

    def test_ab_propose_function_exists(self):
        """ab_propose() should exist and be callable."""
        from three_surgeons.mcp.server import _ab_propose

        assert callable(_ab_propose)

    def test_ab_start_function_exists(self):
        """ab_start() should exist and be callable."""
        from three_surgeons.mcp.server import _ab_start

        assert callable(_ab_start)

    def test_ab_measure_function_exists(self):
        """ab_measure() should exist and be callable."""
        from three_surgeons.mcp.server import _ab_measure

        assert callable(_ab_measure)

    def test_ab_conclude_function_exists(self):
        """ab_conclude() should exist and be callable."""
        from three_surgeons.mcp.server import _ab_conclude

        assert callable(_ab_conclude)

    def test_neurologist_pulse_function_exists(self):
        from three_surgeons.mcp.server import _neurologist_pulse_impl
        assert callable(_neurologist_pulse_impl)

    def test_neurologist_challenge_function_exists(self):
        from three_surgeons.mcp.server import _neurologist_challenge_impl
        assert callable(_neurologist_challenge_impl)

    def test_introspect_function_exists(self):
        from three_surgeons.mcp.server import _introspect_impl
        assert callable(_introspect_impl)

    def test_ask_local_function_exists(self):
        from three_surgeons.mcp.server import _ask_local_impl
        assert callable(_ask_local_impl)

    def test_ask_remote_function_exists(self):
        from three_surgeons.mcp.server import _ask_remote_impl
        assert callable(_ask_remote_impl)

    def test_cardio_review_function_exists(self):
        from three_surgeons.mcp.server import _cardio_review_impl
        assert callable(_cardio_review_impl)

    def test_ab_validate_function_exists(self):
        from three_surgeons.mcp.server import _ab_validate_impl
        assert callable(_ab_validate_impl)

    def test_research_function_exists(self):
        from three_surgeons.mcp.server import _research_impl
        assert callable(_research_impl)


class TestToolDelegation:
    """Tool functions delegate to core/ modules -- no business logic in server."""

    def test_probe_delegates_to_models(self):
        """probe() should call LLMProvider.ping() for each surgeon."""
        from three_surgeons.mcp.server import _probe

        with patch("three_surgeons.mcp.server._build_config") as mock_cfg:
            mock_config = MagicMock()
            mock_cfg.return_value = mock_config

            with patch("three_surgeons.mcp.server.LLMProvider") as mock_provider_cls:
                mock_resp = MagicMock(ok=True, latency_ms=42, content="operational")
                mock_provider_cls.return_value.ping.return_value = mock_resp

                result = _probe()

                assert isinstance(result, dict)
                assert "cardiologist" in result
                assert "neurologist" in result

    def test_sentinel_run_delegates_to_sentinel(self):
        """sentinel_run() should call Sentinel.run_cycle()."""
        from three_surgeons.mcp.server import _sentinel_run

        with patch("three_surgeons.mcp.server.Sentinel") as mock_cls:
            mock_result = MagicMock(
                vectors_checked=8,
                vectors_triggered=2,
                risk_level="medium",
                overall_score=0.55,
                triggered_vectors=[],
                recommendations=[],
            )
            mock_cls.return_value.run_cycle.return_value = mock_result

            result = _sentinel_run("test content with auth tokens")

            mock_cls.return_value.run_cycle.assert_called_once_with(
                "test content with auth tokens"
            )
            assert isinstance(result, dict)
            assert result["vectors_checked"] == 8
            assert result["risk_level"] == "medium"

    def test_gains_gate_delegates_to_gate(self):
        """gains_gate() should call GainsGate.run()."""
        from three_surgeons.mcp.server import _gains_gate

        with patch("three_surgeons.mcp.server._build_config") as mock_cfg, \
             patch("three_surgeons.mcp.server._build_state") as mock_state, \
             patch("three_surgeons.mcp.server._build_evidence") as mock_ev, \
             patch("three_surgeons.mcp.server.GainsGate") as mock_gate_cls:

            mock_result = MagicMock(
                passed=True,
                summary="PASS: 4/4 checks passed",
                duration_ms=12.5,
                checks=[],
            )
            mock_gate_cls.return_value.run.return_value = mock_result

            result = _gains_gate()

            mock_gate_cls.return_value.run.assert_called_once()
            assert isinstance(result, dict)
            assert result["passed"] is True

    def test_consult_delegates_to_surgery_team(self):
        """consult() should call SurgeryTeam.consult()."""
        from three_surgeons.mcp.server import _consult

        with patch("three_surgeons.mcp.server._build_surgery_team") as mock_team_fn:
            mock_result = MagicMock(
                topic="test topic",
                cardiologist_report="cardio says X",
                neurologist_report="neuro says Y",
                total_cost=0.01,
                total_latency_ms=500,
            )
            mock_team_fn.return_value.consult.return_value = mock_result

            result = _consult("test topic")

            mock_team_fn.return_value.consult.assert_called_once_with("test topic")
            assert isinstance(result, dict)
            assert result["topic"] == "test topic"

    def test_cross_examine_delegates_to_surgery_team(self):
        """cross_examine() should call SurgeryTeam.cross_examine()."""
        from three_surgeons.mcp.server import _cross_examine

        with patch("three_surgeons.mcp.server._build_surgery_team") as mock_team_fn:
            mock_result = MagicMock(
                topic="deep topic",
                cardiologist_report="cardio deep analysis",
                neurologist_report="neuro deep analysis",
                synthesis="synthesis here",
                total_cost=0.05,
                total_latency_ms=2000,
            )
            mock_team_fn.return_value.cross_examine.return_value = mock_result

            result = _cross_examine("deep topic", depth="full")

            mock_team_fn.return_value.cross_examine.assert_called_once_with(
                "deep topic", depth="full"
            )
            assert isinstance(result, dict)
            assert "synthesis" in result

    def test_consensus_delegates_to_surgery_team(self):
        """consensus() should call SurgeryTeam.consensus()."""
        from three_surgeons.mcp.server import _consensus

        with patch("three_surgeons.mcp.server._build_surgery_team") as mock_team_fn:
            mock_result = MagicMock(
                claim="test claim",
                cardiologist_confidence=0.8,
                cardiologist_assessment="agree",
                neurologist_confidence=0.6,
                neurologist_assessment="uncertain",
                weighted_score=0.57,
                total_cost=0.003,
            )
            mock_team_fn.return_value.consensus.return_value = mock_result

            result = _consensus("test claim")

            mock_team_fn.return_value.consensus.assert_called_once_with("test claim")
            assert isinstance(result, dict)
            assert result["weighted_score"] == 0.57

    def test_ab_propose_delegates_to_engine(self):
        """ab_propose() should call ABTestEngine.propose()."""
        from three_surgeons.mcp.server import _ab_propose

        with patch("three_surgeons.mcp.server._build_ab_engine") as mock_engine_fn:
            mock_test = MagicMock()
            mock_test.to_dict.return_value = {
                "id": "test-123",
                "param": "temperature",
                "variant_a": "0.7",
                "variant_b": "0.9",
                "hypothesis": "Higher temp improves diversity",
                "status": "proposed",
            }
            mock_engine_fn.return_value.propose.return_value = mock_test

            result = _ab_propose(
                param="temperature",
                variant_a="0.7",
                variant_b="0.9",
                hypothesis="Higher temp improves diversity",
            )

            mock_engine_fn.return_value.propose.assert_called_once_with(
                param="temperature",
                variant_a="0.7",
                variant_b="0.9",
                hypothesis="Higher temp improves diversity",
            )
            assert isinstance(result, dict)
            assert result["param"] == "temperature"

    def test_ab_start_delegates_to_engine(self):
        """ab_start() should call ABTestEngine.start_grace_period()."""
        from three_surgeons.mcp.server import _ab_start

        with patch("three_surgeons.mcp.server._build_ab_engine") as mock_engine_fn:
            mock_test = MagicMock()
            mock_test.to_dict.return_value = {
                "id": "test-123",
                "status": "grace_period",
            }
            mock_engine_fn.return_value.start_grace_period.return_value = mock_test

            result = _ab_start("test-123")

            mock_engine_fn.return_value.start_grace_period.assert_called_once_with(
                "test-123"
            )
            assert isinstance(result, dict)

    def test_ab_measure_delegates_to_engine(self):
        """ab_measure() should call ABTestEngine.measure()."""
        from three_surgeons.mcp.server import _ab_measure

        with patch("three_surgeons.mcp.server._build_ab_engine") as mock_engine_fn:
            mock_engine_fn.return_value.measure.return_value = {
                "test_id": "test-123",
                "metric_a": 0.85,
                "metric_b": 0.90,
                "delta": 0.05,
                "variant_b_better": True,
            }

            result = _ab_measure("test-123", metric_a=0.85, metric_b=0.90)

            mock_engine_fn.return_value.measure.assert_called_once_with(
                "test-123", metric_a=0.85, metric_b=0.90
            )
            assert result["delta"] == 0.05

    def test_ab_conclude_delegates_to_engine(self):
        """ab_conclude() should call ABTestEngine.conclude()."""
        from three_surgeons.mcp.server import _ab_conclude

        with patch("three_surgeons.mcp.server._build_ab_engine") as mock_engine_fn:
            mock_test = MagicMock()
            mock_test.to_dict.return_value = {
                "id": "test-123",
                "status": "concluded",
                "verdict": "variant_b wins",
            }
            mock_engine_fn.return_value.conclude.return_value = mock_test

            result = _ab_conclude("test-123", verdict="variant_b wins")

            mock_engine_fn.return_value.conclude.assert_called_once_with(
                "test-123", "variant_b wins"
            )
            assert result["verdict"] == "variant_b wins"


class TestErrorHandling:
    """Tools handle errors gracefully and return structured error dicts."""

    def test_probe_handles_connection_error(self):
        """probe() should return error info when surgeons unreachable."""
        from three_surgeons.mcp.server import _probe

        with patch("three_surgeons.mcp.server._build_config") as mock_cfg:
            mock_config = MagicMock()
            mock_cfg.return_value = mock_config

            with patch("three_surgeons.mcp.server.LLMProvider") as mock_cls:
                mock_cls.return_value.ping.side_effect = Exception("Connection refused")

                result = _probe()

                # Should return error info, not crash
                assert isinstance(result, dict)
                assert "cardiologist" in result
                assert "error" in result["cardiologist"]

    def test_ab_propose_handles_forbidden_param(self):
        """ab_propose() should return error for forbidden params."""
        from three_surgeons.mcp.server import _ab_propose

        with patch("three_surgeons.mcp.server._build_ab_engine") as mock_engine_fn:
            mock_engine_fn.return_value.propose.side_effect = ValueError(
                "Parameter 'safety_gate' is forbidden"
            )

            result = _ab_propose(
                param="safety_gate",
                variant_a="a",
                variant_b="b",
                hypothesis="test",
            )

            assert isinstance(result, dict)
            assert "error" in result
