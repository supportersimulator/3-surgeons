# tests/test_upgrade_integration.py
"""End-to-end integration test for the upgrade adaptability flow."""
from __future__ import annotations

import json
import time
from pathlib import Path
from unittest.mock import patch

import pytest
import yaml

from three_surgeons.core.config import Config
from three_surgeons.core.upgrade import (
    AdaptivePoller,
    ConfigTracker,
    EcosystemProbe,
    InfraCapability,
    ProbeResult,
    UpgradeAction,
    UpgradeEngine,
    UpgradeEventLog,
    UpgradeTransaction,
)


class TestFullUpgradeFlow:
    """Simulate a complete Phase 1 → Phase 2 upgrade cycle."""

    def test_phase1_to_phase2_silent_upgrade(self, tmp_path: Path) -> None:
        # Setup Phase 1
        config_dir = tmp_path / ".3surgeons"
        config_dir.mkdir()
        config_file = config_dir / "config.yaml"
        config_file.write_text(yaml.dump({
            "schema_version": 1,
            "phase": 1,
        }))

        cfg = Config()
        cfg.phase = 1
        engine = UpgradeEngine(config=cfg, config_dir=config_dir)

        # Probe detects Redis (single path → silent upgrade)
        probe_result = ProbeResult(
            detected_phase=2,
            capabilities=[InfraCapability.REDIS],
        )
        action, details = engine.decide(probe_result)
        assert action == UpgradeAction.SILENT_UPGRADE

        # Execute upgrade
        engine.execute_upgrade(target_phase=2)

        # Verify config updated
        loaded = yaml.safe_load(config_file.read_text())
        assert loaded["phase"] == 2

        # Verify event logged
        log = UpgradeEventLog(config_dir / "upgrade.log")
        entries = log.read_all()
        assert any(e["event"] == "upgrade" for e in entries)

    def test_crash_recovery_restores_phase1(self, tmp_path: Path) -> None:
        config_dir = tmp_path / ".3surgeons"
        config_dir.mkdir()
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
        config_file.write_text(yaml.dump({"phase": 2}))

        # Fresh startup detects crash
        cfg = Config()
        cfg.phase = 2
        engine = UpgradeEngine(config=cfg, config_dir=config_dir)

        assert engine.recovered_from_crash
        loaded = yaml.safe_load(config_file.read_text())
        assert loaded["phase"] == 1

    def test_config_hash_detects_external_change(self, tmp_path: Path) -> None:
        config_file = tmp_path / "config.yaml"
        config_file.write_text(yaml.dump({"phase": 1}))

        tracker = ConfigTracker(config_file)
        tracker.update_stored_hash()
        assert not tracker.has_changed()

        # External tool modifies config
        config_file.write_text(yaml.dump({"phase": 1, "extra": "setting"}))
        assert tracker.has_changed()

    def test_adaptive_poller_lifecycle(self) -> None:
        poller = AdaptivePoller(base_interval=10, max_interval=100)

        assert poller.should_probe()
        poller.mark_probed()
        assert not poller.should_probe()

        # Back off
        poller.on_no_change()
        assert poller.current_interval == 15.0  # 10 * 1.5

        # Reset
        poller.on_change_detected()
        assert poller.current_interval == 10
