"""Tests for Phase 3 IDE event bus detection in UpgradeChecker."""
from __future__ import annotations

from unittest.mock import patch

import pytest

from three_surgeons.core.upgrade import UpgradeChecker


class TestPhase3Detection:

    def test_env_var_detects_phase3(self, monkeypatch):
        """CONTEXTDNA_IDE_BUS env var triggers Phase 3 detection."""
        monkeypatch.setenv("CONTEXTDNA_IDE_BUS", "ws://127.0.0.1:8031")
        # Prevent other probes from interfering
        monkeypatch.delenv("CONTEXTDNA_ADAPTER", raising=False)
        with patch(
            "three_surgeons.core.upgrade.detect_local_backend", return_value=[]
        ), patch(
            "three_surgeons.core.upgrade.EcosystemProbe._check_redis",
            return_value=False,
        ), patch(
            "three_surgeons.core.upgrade.EcosystemProbe._check_contextdna",
            return_value=False,
        ):
            checker = UpgradeChecker()
            result = checker.check()
            assert result.detected_phase == 3

    def test_health_endpoint_detects_phase3(self, monkeypatch):
        """HTTP probe to 127.0.0.1:8031/health triggers Phase 3."""
        monkeypatch.delenv("CONTEXTDNA_IDE_BUS", raising=False)
        monkeypatch.delenv("CONTEXTDNA_ADAPTER", raising=False)
        with patch(
            "three_surgeons.core.upgrade.detect_local_backend", return_value=[]
        ), patch(
            "three_surgeons.core.upgrade.EcosystemProbe._check_redis",
            return_value=False,
        ), patch(
            "three_surgeons.core.upgrade.EcosystemProbe._check_contextdna",
            return_value=False,
        ), patch(
            "three_surgeons.core.upgrade.httpx.get",
        ) as mock_get:
            mock_get.return_value.status_code = 200
            checker = UpgradeChecker()
            result = checker.check()
            assert result.detected_phase == 3

    def test_no_env_var_not_phase3(self, monkeypatch):
        """Without env var or server, phase should not be 3."""
        monkeypatch.delenv("CONTEXTDNA_IDE_BUS", raising=False)
        monkeypatch.delenv("CONTEXTDNA_ADAPTER", raising=False)
        with patch(
            "three_surgeons.core.upgrade.detect_local_backend", return_value=[]
        ), patch(
            "three_surgeons.core.upgrade.EcosystemProbe._check_redis",
            return_value=False,
        ), patch(
            "three_surgeons.core.upgrade.EcosystemProbe._check_contextdna",
            return_value=False,
        ), patch(
            "three_surgeons.core.upgrade.httpx.get",
            side_effect=ConnectionError("no server"),
        ):
            checker = UpgradeChecker()
            result = checker.check()
            assert result.detected_phase != 3
