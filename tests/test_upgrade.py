# tests/test_upgrade.py
"""Tests for the upgrade adaptability engine."""
from __future__ import annotations

import json
import time
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest
import yaml

from three_surgeons.core.upgrade import (
    ConfigTracker,
    EcosystemProbe,
    ProbeResult,
    InfraCapability,
    UpgradeTransaction,
    TransactionStatus,
)
from three_surgeons.core.config import Config


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


class TestTransactionStatus:
    def test_enum_values(self) -> None:
        assert TransactionStatus.IN_PROGRESS.value == "in_progress"
        assert TransactionStatus.COMMITTED.value == "committed"


class TestUpgradeTransaction:
    def _make_config_dir(self, tmp_path: Path) -> Path:
        config_dir = tmp_path / ".3surgeons"
        config_dir.mkdir()
        config_file = config_dir / "config.yaml"
        config_file.write_text(yaml.dump({"phase": 1, "schema_version": 1}))
        return config_dir

    def test_begin_creates_snapshot(self, tmp_path: Path) -> None:
        config_dir = self._make_config_dir(tmp_path)
        tx = UpgradeTransaction(config_dir)
        tx.begin(current_phase=1, target_phase=2)
        assert tx.status == TransactionStatus.IN_PROGRESS
        snapshot_file = config_dir / "upgrade_snapshot.json"
        assert snapshot_file.exists()
        snapshot = json.loads(snapshot_file.read_text())
        assert snapshot["status"] == "in_progress"
        assert snapshot["from_phase"] == 1
        assert snapshot["to_phase"] == 2

    def test_commit_marks_committed(self, tmp_path: Path) -> None:
        config_dir = self._make_config_dir(tmp_path)
        tx = UpgradeTransaction(config_dir)
        tx.begin(current_phase=1, target_phase=2)
        tx.commit()
        assert tx.status == TransactionStatus.COMMITTED
        snapshot = json.loads((config_dir / "upgrade_snapshot.json").read_text())
        assert snapshot["status"] == "committed"

    def test_rollback_restores_config(self, tmp_path: Path) -> None:
        config_dir = self._make_config_dir(tmp_path)
        config_file = config_dir / "config.yaml"
        original_content = config_file.read_text()

        tx = UpgradeTransaction(config_dir)
        tx.begin(current_phase=1, target_phase=2)
        # Simulate upgrade: change config
        config_file.write_text(yaml.dump({"phase": 2, "schema_version": 1}))
        # Rollback
        tx.rollback()
        assert config_file.read_text() == original_content
        assert tx.status is None  # Snapshot cleaned up

    def test_needs_recovery_on_in_progress(self, tmp_path: Path) -> None:
        config_dir = self._make_config_dir(tmp_path)
        tx = UpgradeTransaction(config_dir)
        tx.begin(current_phase=1, target_phase=2)
        # Simulate crash: create new transaction instance (fresh startup)
        tx2 = UpgradeTransaction(config_dir)
        assert tx2.needs_recovery()

    def test_no_recovery_on_committed(self, tmp_path: Path) -> None:
        config_dir = self._make_config_dir(tmp_path)
        tx = UpgradeTransaction(config_dir)
        tx.begin(current_phase=1, target_phase=2)
        tx.commit()
        tx2 = UpgradeTransaction(config_dir)
        assert not tx2.needs_recovery()

    def test_recover_reverts_to_snapshot(self, tmp_path: Path) -> None:
        config_dir = self._make_config_dir(tmp_path)
        config_file = config_dir / "config.yaml"
        original = config_file.read_text()

        tx = UpgradeTransaction(config_dir)
        tx.begin(current_phase=1, target_phase=2)
        config_file.write_text(yaml.dump({"phase": 2}))
        # Simulate crash + fresh startup
        tx2 = UpgradeTransaction(config_dir)
        assert tx2.needs_recovery()
        tx2.recover()
        assert config_file.read_text() == original
