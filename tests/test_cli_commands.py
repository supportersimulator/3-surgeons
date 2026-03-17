"""Tests for CLI command registration and _run_command helper."""
from __future__ import annotations

import sys
from unittest.mock import MagicMock, patch

import pytest
from click.testing import CliRunner

from three_surgeons.cli.main import cli

# Resolve the *module* object (not the function) for patch.object().
# On Python 3.10, "three_surgeons.cli.main" as a string resolves to the
# main *function* re-exported by __init__.py, breaking @patch() decorators.
_cli_main_mod = sys.modules["three_surgeons.cli.main"]


class TestCliCommandsRegistered:
    """Verify all 11 new commands are registered on the CLI group."""

    EXPECTED = [
        "status", "research-status",
        "ab-veto", "ab-queue", "ab-start", "ab-measure", "ab-conclude", "ab-collaborate",
        "research-evidence", "cardio-reverify", "deep-audit",
    ]

    def test_commands_exist(self):
        registered = {cmd.name for cmd in cli.commands.values()} if hasattr(cli, 'commands') else set()
        for name in self.EXPECTED:
            assert name in registered, f"Command '{name}' not registered on CLI"


class TestRunCommand:
    """Test _run_command helper handles gate results correctly."""

    @patch.object(_cli_main_mod, "build_runtime_context")
    @patch.object(_cli_main_mod, "check_requirements")
    def test_blocked_exits_with_error(self, mock_check, mock_build):
        from three_surgeons.core.requirements import GateResult
        mock_build.return_value = MagicMock()
        mock_check.return_value = (GateResult.BLOCKED, ["No state backend"])

        runner = CliRunner()
        result = runner.invoke(cli, ["status"])
        assert result.exit_code != 0

    @patch.object(_cli_main_mod, "build_runtime_context")
    @patch.object(_cli_main_mod, "check_requirements")
    @patch("three_surgeons.core.status_commands.cmd_status")
    def test_proceed_outputs_yaml(self, mock_cmd, mock_check, mock_build):
        from three_surgeons.core.requirements import GateResult, CommandResult
        mock_build.return_value = MagicMock()
        mock_check.return_value = (GateResult.PROCEED, [])
        mock_cmd.return_value = CommandResult(
            success=True, data={"test": "value"}
        )

        runner = CliRunner()
        result = runner.invoke(cli, ["status"])
        assert result.exit_code == 0
        assert "success: true" in result.output or "success:" in result.output

    @patch.object(_cli_main_mod, "build_runtime_context")
    @patch.object(_cli_main_mod, "check_requirements")
    @patch("three_surgeons.core.status_commands.cmd_status")
    def test_degraded_includes_notes(self, mock_cmd, mock_check, mock_build):
        from three_surgeons.core.requirements import GateResult, CommandResult
        mock_build.return_value = MagicMock()
        mock_check.return_value = (GateResult.DEGRADED, ["No neurologist available"])
        mock_cmd.return_value = CommandResult(
            success=True, data={"health": "partial"}
        )

        runner = CliRunner()
        result = runner.invoke(cli, ["status"])
        assert result.exit_code == 0
        assert "degradation_notes" in result.output
        assert "No neurologist available" in result.output
