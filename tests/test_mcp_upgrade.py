# tests/test_mcp_upgrade.py
"""Tests for upgrade MCP tools."""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest


class TestUpgradeMCPTools:
    """Verify upgrade tools are registered in MCP server."""

    def test_probe_tool_exists(self) -> None:
        from three_surgeons.mcp.server import TOOL_NAMES

        assert "upgrade_probe" in TOOL_NAMES

    def test_history_tool_exists(self) -> None:
        from three_surgeons.mcp.server import TOOL_NAMES

        assert "upgrade_history" in TOOL_NAMES

    def test_upgrade_probe_impl_exists(self) -> None:
        from three_surgeons.mcp.server import _upgrade_probe_impl

        assert callable(_upgrade_probe_impl)

    def test_upgrade_history_impl_exists(self) -> None:
        from three_surgeons.mcp.server import _upgrade_history_impl

        assert callable(_upgrade_history_impl)

    @patch("three_surgeons.core.upgrade.EcosystemProbe")
    def test_upgrade_probe_returns_dict(self, mock_probe_cls) -> None:
        """upgrade_probe should return a dict with phase and capabilities."""
        from three_surgeons.core.upgrade import ProbeResult, InfraCapability

        mock_result = ProbeResult(
            detected_phase=2,
            capabilities=[InfraCapability.LOCAL_LLM, InfraCapability.REDIS],
            details={"local_backends": ["mlx"]},
        )
        mock_probe_cls.return_value.run.return_value = mock_result

        from three_surgeons.mcp.server import _upgrade_probe_impl

        with patch("three_surgeons.mcp.server._build_config") as mock_cfg:
            mock_cfg.return_value.phase = 1
            result = _upgrade_probe_impl()

        assert result["detected_phase"] == 2
        assert "local_llm" in result["capabilities"]
        assert "redis" in result["capabilities"]
        assert result["current_phase"] == 1

    def test_upgrade_history_no_file(self, tmp_path) -> None:
        """upgrade_history should return empty list message when no log exists."""
        from three_surgeons.mcp.server import _upgrade_history_impl

        with patch("three_surgeons.mcp.server._upgrade_log_path", return_value=tmp_path / "nonexistent.log"):
            result = _upgrade_history_impl()

        assert result == "No upgrade history."

    def test_upgrade_history_with_entries(self, tmp_path) -> None:
        """upgrade_history should return JSON entries when log exists."""
        log_path = tmp_path / "upgrade.log"
        entry = {"timestamp": "2026-03-10T00:00:00+00:00", "event": "upgrade", "from_phase": 1, "to_phase": 2}
        log_path.write_text(json.dumps(entry) + "\n")

        from three_surgeons.mcp.server import _upgrade_history_impl

        with patch("three_surgeons.mcp.server._upgrade_log_path", return_value=log_path):
            result = _upgrade_history_impl()

        parsed = json.loads(result)
        assert len(parsed) == 1
        assert parsed[0]["event"] == "upgrade"
