# tests/test_mcp_capability_wire.py
"""Tests for capability registry wiring into MCP upgrade_probe tool."""
from __future__ import annotations

from unittest.mock import patch

import pytest


@pytest.fixture(autouse=True)
def _reset_registry():
    """Reset the module-level shared registry between tests."""
    import three_surgeons.mcp.server as srv
    srv._registry = None
    yield
    srv._registry = None


class TestGetRegistry:
    """Shared registry helper returns the same instance on repeat calls."""

    def test_returns_same_instance(self) -> None:
        from three_surgeons.mcp.server import _get_registry

        r1 = _get_registry()
        r2 = _get_registry()
        assert r1 is r2

    def test_returns_capability_registry_type(self) -> None:
        from three_surgeons.core.capability_registry import CapabilityRegistry
        from three_surgeons.mcp.server import _get_registry

        reg = _get_registry()
        assert isinstance(reg, CapabilityRegistry)


class TestUpgradeProbeCapabilityWire:
    """upgrade_probe result includes capability_levels and posture."""

    @patch("three_surgeons.core.upgrade.EcosystemProbe")
    def test_result_has_capability_keys(self, mock_probe_cls, tmp_path) -> None:
        from three_surgeons.core.upgrade import InfraCapability, ProbeResult
        from three_surgeons.mcp.server import _upgrade_probe_impl

        mock_result = ProbeResult(
            detected_phase=2,
            capabilities=[InfraCapability.LOCAL_LLM, InfraCapability.REDIS],
            details={"local_backends": ["mlx"]},
        )
        mock_probe_cls.return_value.run.return_value = mock_result

        with patch("three_surgeons.mcp.server._build_config") as mock_cfg:
            mock_cfg.return_value.phase = 1
            result = _upgrade_probe_impl()

        assert "capability_levels" in result
        assert "posture" in result
        assert isinstance(result["capability_levels"], dict)
        assert result["posture"] in ("nominal", "degraded", "recovering", "safe_mode")

    @patch("three_surgeons.core.upgrade.EcosystemProbe")
    def test_capability_levels_reflect_probe(self, mock_probe_cls, tmp_path) -> None:
        """With LOCAL_LLM detected, LLM_BACKEND should be at least L2."""
        from three_surgeons.core.upgrade import InfraCapability, ProbeResult
        from three_surgeons.mcp.server import _upgrade_probe_impl

        mock_result = ProbeResult(
            detected_phase=2,
            capabilities=[InfraCapability.LOCAL_LLM],
            details={},
        )
        mock_probe_cls.return_value.run.return_value = mock_result

        with patch("three_surgeons.mcp.server._build_config") as mock_cfg:
            mock_cfg.return_value.phase = 1
            result = _upgrade_probe_impl()

        llm_level = result["capability_levels"]["llm_backend"]["level"]
        assert llm_level >= 2

    @patch("three_surgeons.core.upgrade.EcosystemProbe")
    def test_shared_registry_used_across_calls(self, mock_probe_cls) -> None:
        """Both upgrade_probe and capability_status share the same registry."""
        from three_surgeons.core.upgrade import InfraCapability, ProbeResult
        from three_surgeons.mcp.server import _get_registry, _upgrade_probe_impl

        mock_result = ProbeResult(
            detected_phase=1,
            capabilities=[],
            details={},
        )
        mock_probe_cls.return_value.run.return_value = mock_result

        with patch("three_surgeons.mcp.server._build_config") as mock_cfg:
            mock_cfg.return_value.phase = 1
            _upgrade_probe_impl()

        # The registry should now be initialised
        reg = _get_registry()
        assert reg is not None
        snap = reg.snapshot()
        assert "capabilities" in snap


class TestCapabilityStatusSharedRegistry:
    """capability_status uses the shared registry, not a fresh one."""

    @patch("three_surgeons.core.upgrade.EcosystemProbe")
    def test_uses_shared_registry(self, mock_probe_cls) -> None:
        from three_surgeons.core.upgrade import InfraCapability, ProbeResult
        from three_surgeons.mcp.server import _capability_status, _get_registry

        mock_result = ProbeResult(
            detected_phase=1,
            capabilities=[InfraCapability.LOCAL_LLM],
            details={},
        )
        mock_probe_cls.return_value.run.return_value = mock_result

        result = _capability_status()
        reg = _get_registry()

        # The registry returned by _get_registry should be the same one used
        assert result["posture"] == reg.posture.value
