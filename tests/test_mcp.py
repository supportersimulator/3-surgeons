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
        """MCP server should use the bin/3surgeons-mcp launcher."""
        plugin_json = Path(__file__).parent.parent / ".claude-plugin" / "plugin.json"
        data = json.loads(plugin_json.read_text())
        server_cfg = data["mcpServers"]["3-surgeons"]
        assert "3surgeons-mcp" in server_cfg["command"]

    def test_plugin_json_has_homepage(self):
        """plugin.json should declare a homepage."""
        plugin_json = Path(__file__).parent.parent / ".claude-plugin" / "plugin.json"
        data = json.loads(plugin_json.read_text())
        assert "homepage" in data
        assert len(data["homepage"]) > 0

    def test_marketplace_json_exists(self):
        """marketplace.json should exist for plugin install support."""
        marketplace_json = Path(__file__).parent.parent / ".claude-plugin" / "marketplace.json"
        assert marketplace_json.is_file()
        data = json.loads(marketplace_json.read_text())
        assert "plugins" in data
        assert len(data["plugins"]) >= 1


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
        """cross_examine() should call SurgeryTeam.cross_examine_iterative()."""
        from three_surgeons.mcp.server import _cross_examine

        with patch("three_surgeons.mcp.server._build_surgery_team") as mock_team_fn:
            mock_result = MagicMock(
                topic="deep topic",
                cardiologist_report="cardio deep analysis",
                neurologist_report="neuro deep analysis",
                cardiologist_exploration="explore-c",
                neurologist_exploration="explore-n",
                synthesis="synthesis here",
                total_cost=0.05,
                total_latency_ms=2000,
                iteration_count=1,
                mode_used="single",
                escalation_needed=False,
                unresolved_summary=None,
            )
            mock_team_fn.return_value.cross_examine_iterative.return_value = mock_result

            result = _cross_examine("deep topic", depth="full")

            from three_surgeons.core.cross_exam import ReviewMode
            mock_team_fn.return_value.cross_examine_iterative.assert_called_once_with(
                "deep topic", mode=ReviewMode.SINGLE, depth="full"
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


class TestCrossExamineMode:
    """cross_examine MCP tool accepts mode parameter and delegates to cross_examine_iterative."""

    def test_cross_examine_accepts_mode_parameter(self):
        """_cross_examine() should accept a mode parameter."""
        import inspect
        from three_surgeons.mcp.server import _cross_examine

        sig = inspect.signature(_cross_examine)
        assert "mode" in sig.parameters, "mode parameter missing from _cross_examine"

    def test_cross_examine_passes_mode_to_iterative(self):
        """_cross_examine() should call cross_examine_iterative with parsed ReviewMode."""
        from three_surgeons.mcp.server import _cross_examine

        with patch("three_surgeons.mcp.server._build_surgery_team") as mock_team_fn:
            mock_result = MagicMock(
                topic="test topic",
                cardiologist_report="cardio",
                neurologist_report="neuro",
                cardiologist_exploration="explore-c",
                neurologist_exploration="explore-n",
                synthesis="synth",
                total_cost=0.05,
                total_latency_ms=2000,
                iteration_count=1,
                mode_used="single",
                escalation_needed=False,
                unresolved_summary=None,
            )
            mock_team_fn.return_value.cross_examine_iterative.return_value = mock_result

            result = _cross_examine("test topic", mode="iterative")

            mock_team_fn.return_value.cross_examine_iterative.assert_called_once()
            call_kwargs = mock_team_fn.return_value.cross_examine_iterative.call_args
            # Verify mode was parsed from string to ReviewMode
            from three_surgeons.core.cross_exam import ReviewMode
            assert call_kwargs.kwargs.get("mode") == ReviewMode.ITERATIVE or \
                   call_kwargs[1].get("mode") == ReviewMode.ITERATIVE

    def test_cross_examine_default_mode_is_single(self):
        """_cross_examine() should default mode to 'single'."""
        import inspect
        from three_surgeons.mcp.server import _cross_examine

        sig = inspect.signature(_cross_examine)
        default = sig.parameters["mode"].default
        assert default == "single"

    def test_cross_examine_returns_iteration_metadata(self):
        """_cross_examine() should include iteration_count, mode_used in result."""
        from three_surgeons.mcp.server import _cross_examine

        with patch("three_surgeons.mcp.server._build_surgery_team") as mock_team_fn:
            mock_result = MagicMock(
                topic="t",
                cardiologist_report="c",
                neurologist_report="n",
                cardiologist_exploration="ec",
                neurologist_exploration="en",
                synthesis="s",
                total_cost=0.01,
                total_latency_ms=100,
                iteration_count=3,
                mode_used="iterative",
                escalation_needed=True,
                unresolved_summary="not resolved",
            )
            mock_team_fn.return_value.cross_examine_iterative.return_value = mock_result

            result = _cross_examine("t", mode="iterative")

            assert result["iteration_count"] == 3
            assert result["mode_used"] == "iterative"
            assert result["escalation_needed"] is True
            assert result["unresolved_summary"] == "not resolved"


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


class TestPluginStructure:
    """Verify complete plugin structure matches Claude Code conventions."""

    def test_hooks_json_exists(self):
        hooks_json = Path(__file__).parent.parent / "hooks" / "hooks.json"
        assert hooks_json.is_file()
        data = json.loads(hooks_json.read_text())
        assert "hooks" in data
        assert "SessionStart" in data["hooks"]

    def test_hooks_json_uses_polyglot_wrapper(self):
        hooks_json = Path(__file__).parent.parent / "hooks" / "hooks.json"
        data = json.loads(hooks_json.read_text())
        cmd = data["hooks"]["SessionStart"][0]["hooks"][0]["command"]
        assert "run-hook.cmd" in cmd

    def test_session_start_script_exists(self):
        script = Path(__file__).parent.parent / "hooks" / "session-start"
        assert script.is_file()

    def test_polyglot_wrapper_exists(self):
        wrapper = Path(__file__).parent.parent / "hooks" / "run-hook.cmd"
        assert wrapper.is_file()

    def test_mcp_launcher_exists(self):
        launcher = Path(__file__).parent.parent / "bin" / "3surgeons-mcp"
        assert launcher.is_file()

    def test_all_skills_have_frontmatter(self):
        """Every SKILL.md must have YAML frontmatter with name and description."""
        skills_dir = Path(__file__).parent.parent / "skills"
        skill_files = list(skills_dir.glob("*/SKILL.md"))
        assert len(skill_files) >= 13, f"Expected >= 13 skills, found {len(skill_files)}"
        for sf in skill_files:
            content = sf.read_text()
            assert content.startswith("---"), f"{sf} missing YAML frontmatter"
            # Check frontmatter has name and description
            frontmatter_end = content.index("---", 3)
            frontmatter = content[3:frontmatter_end]
            assert "name:" in frontmatter, f"{sf} missing name in frontmatter"
            assert "description:" in frontmatter, f"{sf} missing description in frontmatter"

    def test_commands_have_frontmatter(self):
        """Every command .md must have YAML frontmatter with description."""
        commands_dir = Path(__file__).parent.parent / "commands"
        cmd_files = list(commands_dir.glob("*.md"))
        assert len(cmd_files) >= 6, f"Expected >= 6 commands, found {len(cmd_files)}"
        for cf in cmd_files:
            content = cf.read_text()
            assert content.startswith("---"), f"{cf} missing YAML frontmatter"
            frontmatter_end = content.index("---", 3)
            frontmatter = content[3:frontmatter_end]
            assert "description:" in frontmatter, f"{cf} missing description"

    def test_session_start_has_json_escape(self):
        """Session start hook must properly escape JSON."""
        script = Path(__file__).parent.parent / "hooks" / "session-start"
        content = script.read_text()
        assert "escape_for_json" in content, "Missing JSON escape function"
        assert "hookSpecificOutput" in content, "Missing hookSpecificOutput format"
        assert "additional_context" in content, "Missing additional_context format"

    @property
    def plugin_root(self):
        return Path(__file__).parent.parent

    def test_cursor_plugin_json_exists(self):
        cursor = self.plugin_root / ".cursor-plugin" / "plugin.json"
        assert cursor.exists(), ".cursor-plugin/plugin.json missing"

    def test_cursor_plugin_json_valid(self):
        import json
        cursor = self.plugin_root / ".cursor-plugin" / "plugin.json"
        data = json.loads(cursor.read_text())
        assert data["name"] == "3-surgeons"
        assert "skills" in data

    def test_license_exists(self):
        assert (self.plugin_root / "LICENSE").exists(), "LICENSE file missing"

    def test_gitattributes_exists(self):
        assert (self.plugin_root / ".gitattributes").exists(), ".gitattributes file missing"

    def test_env_example_exists(self):
        assert (self.plugin_root / ".env.example").exists(), ".env.example file missing"

    def test_env_example_no_real_keys(self):
        content = (self.plugin_root / ".env.example").read_text()
        # Should only have empty values (key=) not actual keys
        for line in content.splitlines():
            line = line.strip()
            if "=" in line and not line.startswith("#"):
                key, value = line.split("=", 1)
                assert value.strip() == "", f"Non-empty value in .env.example for {key}"
