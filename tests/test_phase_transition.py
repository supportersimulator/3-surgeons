# tests/test_phase_transition.py
"""E2E tests for Phase 1 → Phase 2 transition."""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from three_surgeons.core.config import Config
from three_surgeons.core.config_resolver import ConfigResolver
from three_surgeons.core.chooser import choose_integration_depth, IntegrationDepth
from three_surgeons.core.migration import (
    EvidenceMigrator,
    MemoryMigrationDestination,
)
from three_surgeons.core.state import resolve_state_backend, SQLiteBackend, MemoryBackend
from three_surgeons.core.upgrade import (
    EcosystemProbe,
    InfraCapability,
    UpgradeEngine,
    UpgradeTransaction,
)


class TestPhase1ToPhase2Minimal:
    """E2E: Phase 1 user detects Redis → Minimal upgrade."""

    def test_full_flow(self, tmp_path: Path) -> None:
        # Phase 1 state: SQLite backend, no config file
        config = Config()
        assert config.phase == 1

        # Resolver detects Redis via probe
        with patch.object(ConfigResolver, "_probe_redis", return_value=True), \
             patch.object(ConfigResolver, "_probe_contextdna", return_value=False):
            resolver = ConfigResolver(config_dir=tmp_path, probe=True)
            state_config = resolver.resolve_state()
            assert state_config.backend == "redis"

        # Chooser recommends Minimal
        plan = choose_integration_depth(
            capabilities={},
            redis_available=True,
            contextdna_available=False,
        )
        assert plan is not None
        assert plan.depth == IntegrationDepth.MINIMAL

        # Write config via resolver
        resolver.write_toml({"state": {"backend": "redis"}})
        assert (tmp_path / "config.toml").is_file()

        # Verify config persisted
        resolver2 = ConfigResolver(config_dir=tmp_path, probe=False)
        assert resolver2.resolve_state().backend == "redis"


class TestPhase1ToPhase2Standard:
    """E2E: Phase 1 user with Redis + ContextDNA → Standard upgrade with evidence migration."""

    def _create_evidence_db(self, db_path: Path) -> None:
        conn = sqlite3.connect(str(db_path))
        conn.execute("""
            CREATE TABLE learnings (
                id INTEGER PRIMARY KEY, key TEXT UNIQUE,
                value TEXT, grade TEXT DEFAULT 'anecdotal',
                observations INTEGER DEFAULT 1,
                created_at TEXT, updated_at TEXT
            )
        """)
        conn.execute(
            "INSERT INTO learnings (key, value, grade) VALUES (?, ?, ?)",
            ("gpu-lock", "Always use file lock for GPU", "case_series"),
        )
        conn.commit()
        conn.close()

    def test_full_flow_with_migration(self, tmp_path: Path) -> None:
        # Setup evidence DB
        db_path = tmp_path / "evidence.db"
        self._create_evidence_db(db_path)

        # Capability negotiation returns evidence_store
        caps = {
            "features": ["evidence_store"],
            "endpoints": {"evidence": "/api/evidence"},
        }
        plan = choose_integration_depth(
            capabilities=caps,
            redis_available=True,
            contextdna_available=True,
        )
        assert plan is not None
        assert plan.depth == IntegrationDepth.STANDARD

        # Migrate evidence to memory destination (test stand-in)
        dest = MemoryMigrationDestination()
        migrator = EvidenceMigrator(source_db=db_path, destination=dest)

        # Dry run first
        dry = migrator.dry_run()
        assert dry.would_migrate == 1
        assert len(dest.items) == 0

        # Actual migration
        result = migrator.migrate()
        assert result.migrated == 1
        assert result.verified is True
        assert len(dest.items) == 1
        assert dest.items[0]["grade"] == "case_series"  # UP-ONLY preserved


class TestUpgradeTransactionRollback:
    """Verify upgrade transaction rollback restores previous state."""

    def test_rollback_restores_config(self, tmp_path: Path) -> None:
        config_dir = tmp_path / "config"
        config_dir.mkdir()
        config_path = config_dir / "config.yaml"
        config_path.write_text("phase: 1\n")

        tx = UpgradeTransaction(config_dir)
        tx.begin(current_phase=1, target_phase=2)

        # Simulate config change
        config_path.write_text("phase: 2\n")

        # Rollback
        tx.rollback()

        # Config should be restored
        assert config_path.read_text() == "phase: 1\n"

    def test_crash_recovery_detects_interrupted(self, tmp_path: Path) -> None:
        config_dir = tmp_path / "config"
        config_dir.mkdir()
        config_path = config_dir / "config.yaml"
        config_path.write_text("phase: 1\n")

        tx = UpgradeTransaction(config_dir)
        tx.begin(current_phase=1, target_phase=2)

        # Simulate crash — don't commit
        # New transaction should detect interrupted state
        tx2 = UpgradeTransaction(config_dir)
        assert tx2.needs_recovery() is True
        recovery_info = tx2.recover()
        assert recovery_info is not None
        assert recovery_info["from_phase"] == 1


class TestPhaseDetectionConsistency:
    """Verify ConfigResolver and EcosystemProbe agree on phase."""

    def test_resolver_and_probe_agree(self, tmp_path: Path) -> None:
        with patch.object(ConfigResolver, "_probe_redis", return_value=True), \
             patch.object(ConfigResolver, "_probe_contextdna", return_value=False), \
             patch.object(EcosystemProbe, "_check_redis", return_value=True), \
             patch.object(EcosystemProbe, "_check_contextdna", return_value=False), \
             patch("three_surgeons.core.config.detect_local_backend", return_value=[]):
            resolver = ConfigResolver(config_dir=tmp_path, probe=True)
            state = resolver.resolve_state()

            probe = EcosystemProbe(config_resolver=resolver)
            result = probe.run()

            # Both should detect Redis → Phase 2
            assert state.backend == "redis"
            assert result.detected_phase == 2


class TestBackwardCompatibility:
    """Phase 1 users with no config file should be completely unaffected."""

    def test_no_config_stays_phase1(self, tmp_path: Path) -> None:
        resolver = ConfigResolver(config_dir=tmp_path, probe=False)
        state = resolver.resolve_state()
        assert state.backend == "sqlite"

        backend = resolve_state_backend(resolver, sqlite_fallback_path=str(tmp_path / "s.db"))
        assert isinstance(backend, SQLiteBackend)

    def test_chooser_returns_none_without_infra(self) -> None:
        plan = choose_integration_depth(
            capabilities={},
            redis_available=False,
            contextdna_available=False,
        )
        assert plan is None
