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
    AdaptivePoller,
    ConfigTracker,
    EcosystemProbe,
    NudgeDetector,
    ProbeResult,
    InfraCapability,
    UpgradeTransaction,
    TransactionStatus,
    UpgradeEventLog,
    UpgradeEngine,
    UpgradeAction,
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


class TestUpgradeEventLog:
    def test_log_event(self, tmp_path: Path) -> None:
        log = UpgradeEventLog(tmp_path / "upgrade.log")
        log.record("upgrade", from_phase=1, to_phase=2, details="Silent upgrade")
        entries = log.read_all()
        assert len(entries) == 1
        assert entries[0]["event"] == "upgrade"
        assert entries[0]["from_phase"] == 1

    def test_append_only(self, tmp_path: Path) -> None:
        log = UpgradeEventLog(tmp_path / "upgrade.log")
        log.record("upgrade", from_phase=1, to_phase=2)
        log.record("revert", from_phase=2, to_phase=1)
        entries = log.read_all()
        assert len(entries) == 2

    def test_human_readable(self, tmp_path: Path) -> None:
        log_path = tmp_path / "upgrade.log"
        log = UpgradeEventLog(log_path)
        log.record("probe", details="No new infra")
        content = log_path.read_text()
        assert "probe" in content
        assert "No new infra" in content


class TestUpgradeAction:
    def test_enum(self) -> None:
        assert UpgradeAction.SILENT_UPGRADE.value == "silent_upgrade"
        assert UpgradeAction.INTERACTIVE_CHOOSER.value == "interactive_chooser"
        assert UpgradeAction.NO_ACTION.value == "no_action"
        assert UpgradeAction.SILENT_DOWNGRADE.value == "silent_downgrade"


class TestUpgradeEngine:
    def _make_engine(self, tmp_path: Path, phase: int = 1) -> UpgradeEngine:
        config_dir = tmp_path / ".3surgeons"
        config_dir.mkdir(parents=True)
        config_file = config_dir / "config.yaml"
        config_file.write_text(yaml.dump({"phase": phase, "schema_version": 1}))
        cfg = Config()
        cfg.phase = phase
        return UpgradeEngine(config=cfg, config_dir=config_dir)

    def test_no_upgrade_same_phase(self, tmp_path: Path) -> None:
        engine = self._make_engine(tmp_path, phase=1)
        probe_result = ProbeResult(detected_phase=1)
        action, details = engine.decide(probe_result)
        assert action == UpgradeAction.NO_ACTION

    def test_silent_upgrade_single_path(self, tmp_path: Path) -> None:
        engine = self._make_engine(tmp_path, phase=1)
        probe_result = ProbeResult(
            detected_phase=2,
            capabilities=[InfraCapability.REDIS],
        )
        action, details = engine.decide(probe_result)
        assert action == UpgradeAction.SILENT_UPGRADE
        assert details["target_phase"] == 2

    def test_interactive_chooser_multiple_paths(self, tmp_path: Path) -> None:
        engine = self._make_engine(tmp_path, phase=1)
        probe_result = ProbeResult(
            detected_phase=2,
            capabilities=[InfraCapability.REDIS, InfraCapability.CONTEXTDNA],
        )
        action, details = engine.decide(probe_result)
        assert action == UpgradeAction.INTERACTIVE_CHOOSER

    def test_silent_downgrade(self, tmp_path: Path) -> None:
        engine = self._make_engine(tmp_path, phase=2)
        probe_result = ProbeResult(detected_phase=1, capabilities=[])
        action, details = engine.decide(probe_result)
        assert action == UpgradeAction.SILENT_DOWNGRADE
        assert details["target_phase"] == 1

    def test_execute_upgrade_creates_transaction(self, tmp_path: Path) -> None:
        engine = self._make_engine(tmp_path, phase=1)
        engine.execute_upgrade(target_phase=2)
        # Config should now say phase 2
        config_file = tmp_path / ".3surgeons" / "config.yaml"
        loaded = yaml.safe_load(config_file.read_text())
        assert loaded["phase"] == 2

    def test_crash_recovery_on_init(self, tmp_path: Path) -> None:
        """Engine detects interrupted upgrade on init and recovers."""
        config_dir = tmp_path / ".3surgeons"
        config_dir.mkdir(parents=True)
        config_file = config_dir / "config.yaml"
        config_file.write_text(yaml.dump({"phase": 1}))

        # Simulate interrupted upgrade
        snapshot = {
            "status": "in_progress",
            "from_phase": 1,
            "to_phase": 2,
            "config_backup": yaml.dump({"phase": 1}),
            "timestamp": time.time(),
        }
        (config_dir / "upgrade_snapshot.json").write_text(json.dumps(snapshot))
        config_file.write_text(yaml.dump({"phase": 2}))  # partially upgraded

        cfg = Config()
        cfg.phase = 2
        engine = UpgradeEngine(config=cfg, config_dir=config_dir)
        # Engine should auto-recover
        assert engine.recovered_from_crash
        loaded = yaml.safe_load(config_file.read_text())
        assert loaded["phase"] == 1


class TestAdaptivePoller:
    def test_initial_interval(self) -> None:
        poller = AdaptivePoller(base_interval=300)
        assert poller.current_interval == 300

    def test_backoff_on_no_change(self) -> None:
        poller = AdaptivePoller(base_interval=300, max_interval=3600)
        poller.on_no_change()
        assert poller.current_interval > 300
        # Keep backing off
        for _ in range(20):
            poller.on_no_change()
        assert poller.current_interval <= 3600

    def test_reset_on_change(self) -> None:
        poller = AdaptivePoller(base_interval=300, max_interval=3600)
        for _ in range(10):
            poller.on_no_change()
        assert poller.current_interval > 300
        poller.on_change_detected()
        assert poller.current_interval == 300

    def test_should_probe(self) -> None:
        poller = AdaptivePoller(base_interval=1)  # 1 second for testing
        assert poller.should_probe()  # First time always true
        poller.mark_probed()
        assert not poller.should_probe()  # Just probed


class TestNudgeDetector:
    def test_no_nudge_below_thresholds(self) -> None:
        detector = NudgeDetector(
            evidence_count=10,
            cross_exam_count=3,
            config_edit_count=1,
        )
        assert not detector.should_nudge()

    def test_nudge_on_evidence_threshold(self) -> None:
        detector = NudgeDetector(
            evidence_count=51,
            cross_exam_count=0,
            config_edit_count=0,
        )
        assert detector.should_nudge()
        assert "evidence" in detector.reason().lower()

    def test_nudge_on_cross_exam_threshold(self) -> None:
        detector = NudgeDetector(
            evidence_count=0,
            cross_exam_count=11,
            config_edit_count=0,
        )
        assert detector.should_nudge()

    def test_nudge_on_config_edits(self) -> None:
        detector = NudgeDetector(
            evidence_count=0,
            cross_exam_count=0,
            config_edit_count=6,
        )
        assert detector.should_nudge()

    def test_nudge_disabled(self) -> None:
        detector = NudgeDetector(
            evidence_count=100,
            cross_exam_count=100,
            config_edit_count=100,
            nudge_enabled=False,
        )
        assert not detector.should_nudge()
