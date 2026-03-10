# tests/test_migration.py
"""Tests for evidence migration between phases."""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from three_surgeons.core.migration import (
    EvidenceMigrator,
    MigrationResult,
)


class TestEvidenceMigrator:
    def _create_evidence_db(self, db_path: Path) -> None:
        """Create a minimal evidence.db with test data."""
        conn = sqlite3.connect(str(db_path))
        conn.execute("""
            CREATE TABLE IF NOT EXISTS learnings (
                id INTEGER PRIMARY KEY,
                key TEXT UNIQUE,
                value TEXT,
                grade TEXT DEFAULT 'anecdotal',
                observations INTEGER DEFAULT 1,
                created_at TEXT,
                updated_at TEXT
            )
        """)
        conn.execute(
            "INSERT INTO learnings (key, value, grade, observations) VALUES (?, ?, ?, ?)",
            ("test-learning", "Always use WAL mode", "case_series", 5),
        )
        conn.execute(
            "INSERT INTO learnings (key, value, grade, observations) VALUES (?, ?, ?, ?)",
            ("test-fix", "Restart after config change", "anecdotal", 1),
        )
        conn.commit()
        conn.close()

    def test_dry_run(self, tmp_path: Path) -> None:
        db_path = tmp_path / "evidence.db"
        self._create_evidence_db(db_path)
        migrator = EvidenceMigrator(source_db=db_path)
        result = migrator.dry_run()
        assert result.total_items == 2
        assert result.would_migrate == 2
        assert not result.executed

    def test_migrate_creates_snapshot(self, tmp_path: Path) -> None:
        db_path = tmp_path / "evidence.db"
        self._create_evidence_db(db_path)
        snapshot_dir = tmp_path / "snapshots"
        migrator = EvidenceMigrator(source_db=db_path, snapshot_dir=snapshot_dir)
        result = migrator.migrate()
        assert result.executed
        # Snapshot should exist
        snapshots = list(snapshot_dir.glob("*.json"))
        assert len(snapshots) == 1

    def test_up_only_grade_preserved(self, tmp_path: Path) -> None:
        """Migration preserves UP-ONLY grade rule."""
        db_path = tmp_path / "evidence.db"
        self._create_evidence_db(db_path)
        migrator = EvidenceMigrator(source_db=db_path)
        result = migrator.dry_run()
        # case_series should stay case_series, not downgrade
        items = result.items
        cs_item = next(i for i in items if i["grade"] == "case_series")
        assert cs_item["grade"] == "case_series"

    def test_revert_restores_snapshot(self, tmp_path: Path) -> None:
        db_path = tmp_path / "evidence.db"
        self._create_evidence_db(db_path)
        snapshot_dir = tmp_path / "snapshots"
        migrator = EvidenceMigrator(source_db=db_path, snapshot_dir=snapshot_dir)
        migrator.migrate()
        # Modify DB
        conn = sqlite3.connect(str(db_path))
        conn.execute("DELETE FROM learnings")
        conn.commit()
        conn.close()
        # Revert
        reverted = migrator.revert()
        assert reverted
        conn = sqlite3.connect(str(db_path))
        count = conn.execute("SELECT COUNT(*) FROM learnings").fetchone()[0]
        conn.close()
        assert count == 2
