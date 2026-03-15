"""Tests for capability-adaptive MCP tool implementations."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest


class TestRunTool:
    """Test the _run_tool shared helper."""

    @patch("three_surgeons.mcp.server.build_runtime_context")
    @patch("three_surgeons.mcp.server.check_requirements")
    @patch("three_surgeons.mcp.server._build_config")
    def test_blocked_returns_blocked_dict(self, mock_config, mock_check, mock_build):
        from three_surgeons.core.requirements import GateResult
        from three_surgeons.mcp.server import _run_tool

        mock_config.return_value = MagicMock()
        mock_build.return_value = MagicMock()
        mock_check.return_value = (GateResult.BLOCKED, ["No state backend"])

        result = _run_tool(MagicMock(), lambda ctx: None)
        assert result["blocked"] is True
        assert "No state backend" in result["blocked_reason"]

    @patch("three_surgeons.mcp.server.build_runtime_context")
    @patch("three_surgeons.mcp.server.check_requirements")
    @patch("three_surgeons.mcp.server._build_config")
    def test_proceed_returns_command_result(self, mock_config, mock_check, mock_build):
        from three_surgeons.core.requirements import CommandResult, GateResult
        from three_surgeons.mcp.server import _run_tool

        mock_config.return_value = MagicMock()
        mock_build.return_value = MagicMock()
        mock_check.return_value = (GateResult.PROCEED, [])

        cmd = MagicMock(return_value=CommandResult(success=True, data={"key": "val"}))
        result = _run_tool(MagicMock(), cmd)
        assert result["success"] is True
        assert result["data"]["key"] == "val"

    @patch("three_surgeons.mcp.server.build_runtime_context")
    @patch("three_surgeons.mcp.server.check_requirements")
    @patch("three_surgeons.mcp.server._build_config")
    def test_degraded_adds_notes(self, mock_config, mock_check, mock_build):
        from three_surgeons.core.requirements import CommandResult, GateResult
        from three_surgeons.mcp.server import _run_tool

        mock_config.return_value = MagicMock()
        mock_build.return_value = MagicMock()
        mock_check.return_value = (GateResult.DEGRADED, ["Only 1 surgeon"])

        cmd = MagicMock(return_value=CommandResult(success=True, data={}))
        result = _run_tool(MagicMock(), cmd)
        assert result["success"] is True
        assert "Only 1 surgeon" in result["degradation_notes"]


class TestCapToolFunctions:
    """Test that each _cap_* function calls _run_tool correctly."""

    @patch("three_surgeons.mcp.server._run_tool")
    def test_cap_status(self, mock_run):
        from three_surgeons.mcp.server import _cap_status
        mock_run.return_value = {"success": True}
        result = _cap_status()
        mock_run.assert_called_once()
        assert result["success"] is True

    @patch("three_surgeons.mcp.server._run_tool")
    def test_cap_ab_veto(self, mock_run):
        from three_surgeons.mcp.server import _cap_ab_veto
        mock_run.return_value = {"success": True}
        _cap_ab_veto(test_id="t1", reason="bad")
        mock_run.assert_called_once()

    @patch("three_surgeons.mcp.server._run_tool")
    def test_cap_deep_audit(self, mock_run):
        from three_surgeons.mcp.server import _cap_deep_audit
        mock_run.return_value = {"success": True}
        _cap_deep_audit(topic="security")
        mock_run.assert_called_once()
