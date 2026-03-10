# tests/test_upgrade.py
"""Tests for the upgrade adaptability engine."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from three_surgeons.core.upgrade import (
    ConfigTracker,
    EcosystemProbe,
    ProbeResult,
    InfraCapability,
)


class TestInfraCapability:
    def test_enum_values(self) -> None:
        assert InfraCapability.LOCAL_LLM.value == "local_llm"
        assert InfraCapability.REDIS.value == "redis"
        assert InfraCapability.CONTEXTDNA.value == "contextdna"
        assert InfraCapability.IDE_EVENT_BUS.value == "ide_event_bus"


class TestEcosystemProbe:
    def test_probe_phase1_no_infra(self) -> None:
        """No external infra → Phase 1."""
        probe = EcosystemProbe()
        with patch.object(probe, "_check_redis", return_value=False), \
             patch.object(probe, "_check_contextdna", return_value=False), \
             patch.object(probe, "_check_ide_event_bus", return_value=False), \
             patch("three_surgeons.core.upgrade.detect_local_backend", return_value=[{"provider": "ollama"}]):
            result = probe.run()
            assert result.detected_phase == 1
            assert InfraCapability.LOCAL_LLM in result.capabilities

    def test_probe_phase2_redis(self) -> None:
        """Redis available → Phase 2."""
        probe = EcosystemProbe()
        with patch.object(probe, "_check_redis", return_value=True), \
             patch.object(probe, "_check_contextdna", return_value=False), \
             patch.object(probe, "_check_ide_event_bus", return_value=False), \
             patch("three_surgeons.core.upgrade.detect_local_backend", return_value=[]):
            result = probe.run()
            assert result.detected_phase == 2
            assert InfraCapability.REDIS in result.capabilities

    def test_probe_phase2_contextdna(self) -> None:
        """ContextDNA adapter available → Phase 2."""
        probe = EcosystemProbe()
        with patch.object(probe, "_check_redis", return_value=False), \
             patch.object(probe, "_check_contextdna", return_value=True), \
             patch.object(probe, "_check_ide_event_bus", return_value=False), \
             patch("three_surgeons.core.upgrade.detect_local_backend", return_value=[]):
            result = probe.run()
            assert result.detected_phase == 2
            assert InfraCapability.CONTEXTDNA in result.capabilities

    def test_probe_phase3_ide(self) -> None:
        """IDE event bus → Phase 3."""
        probe = EcosystemProbe()
        with patch.object(probe, "_check_redis", return_value=True), \
             patch.object(probe, "_check_contextdna", return_value=True), \
             patch.object(probe, "_check_ide_event_bus", return_value=True), \
             patch("three_surgeons.core.upgrade.detect_local_backend", return_value=[]):
            result = probe.run()
            assert result.detected_phase == 3

    def test_multiple_upgrade_paths(self) -> None:
        """Multiple infra detected → multiple_paths flag."""
        probe = EcosystemProbe()
        with patch.object(probe, "_check_redis", return_value=True), \
             patch.object(probe, "_check_contextdna", return_value=True), \
             patch.object(probe, "_check_ide_event_bus", return_value=False), \
             patch("three_surgeons.core.upgrade.detect_local_backend", return_value=[{"provider": "ollama"}]):
            result = probe.run()
            assert result.detected_phase == 2
            assert len(result.capabilities) >= 2


class TestConfigTracker:
    def test_compute_hash(self, tmp_path: Path) -> None:
        config_file = tmp_path / "config.yaml"
        config_file.write_text("phase: 1\nschema_version: 1\n")
        tracker = ConfigTracker(config_file)
        h = tracker.compute_hash()
        assert len(h) == 64  # SHA256 hex digest
        # Same content → same hash
        assert tracker.compute_hash() == h

    def test_hash_changes_on_content_change(self, tmp_path: Path) -> None:
        config_file = tmp_path / "config.yaml"
        config_file.write_text("phase: 1\n")
        tracker = ConfigTracker(config_file)
        h1 = tracker.compute_hash()
        config_file.write_text("phase: 2\n")
        h2 = tracker.compute_hash()
        assert h1 != h2

    def test_has_changed_detects_external_edit(self, tmp_path: Path) -> None:
        config_file = tmp_path / "config.yaml"
        config_file.write_text("phase: 1\n")
        tracker = ConfigTracker(config_file)
        tracker.update_stored_hash()
        assert not tracker.has_changed()
        config_file.write_text("phase: 2\n")
        assert tracker.has_changed()

    def test_increment_sequence(self, tmp_path: Path) -> None:
        config_file = tmp_path / "config.yaml"
        config_file.write_text("phase: 1\n")
        tracker = ConfigTracker(config_file)
        assert tracker.sequence == 0
        tracker.increment_sequence()
        assert tracker.sequence == 1
        tracker.increment_sequence()
        assert tracker.sequence == 2

    def test_missing_file_hash(self, tmp_path: Path) -> None:
        tracker = ConfigTracker(tmp_path / "nonexistent.yaml")
        h = tracker.compute_hash()
        assert h is None
