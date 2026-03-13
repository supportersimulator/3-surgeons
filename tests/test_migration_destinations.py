"""Tests for evidence migration destinations (Phase 2)."""
from __future__ import annotations

import hashlib
import json
from typing import Any, Dict, List

import pytest

from three_surgeons.core.migration import (
    MigrationDestination,
    MemoryMigrationDestination,
    MigrationResult,
)


class TestMigrationDestination:
    def test_memory_destination_write_batch(self) -> None:
        """MemoryMigrationDestination stores items in-memory."""
        dest = MemoryMigrationDestination()
        items = [
            {"key": "learning-1", "value": "Always use WAL", "grade": "case_series"},
            {"key": "learning-2", "value": "Restart after config", "grade": "anecdotal"},
        ]
        count = dest.write_batch(items)
        assert count == 2
        assert len(dest.items) == 2

    def test_memory_destination_verify(self) -> None:
        """Verify round-trip: checksums match after write."""
        dest = MemoryMigrationDestination()
        items = [
            {"key": "k1", "value": "v1", "grade": "anecdotal"},
        ]
        dest.write_batch(items)
        checksum = hashlib.sha256(json.dumps(items[0], sort_keys=True).encode()).hexdigest()
        assert dest.verify({"k1": checksum}) is True

    def test_memory_destination_verify_mismatch(self) -> None:
        """Verify fails when checksum doesn't match."""
        dest = MemoryMigrationDestination()
        items = [{"key": "k1", "value": "v1", "grade": "anecdotal"}]
        dest.write_batch(items)
        assert dest.verify({"k1": "bad_checksum"}) is False

    def test_memory_destination_clear(self) -> None:
        """Clear removes all items (for rollback)."""
        dest = MemoryMigrationDestination()
        dest.write_batch([{"key": "k1", "value": "v1", "grade": "anecdotal"}])
        dest.clear()
        assert len(dest.items) == 0


from unittest.mock import MagicMock, patch


class TestRedisMigrationDestination:
    def test_write_batch_stores_as_hashes(self) -> None:
        """Each item written as a Redis hash."""
        from three_surgeons.core.migration import RedisMigrationDestination

        mock_redis = MagicMock()
        dest = RedisMigrationDestination(client=mock_redis, key_prefix="3surgeons:evidence")
        items = [
            {"key": "learning-1", "value": "WAL mode", "grade": "case_series"},
        ]
        count = dest.write_batch(items)
        assert count == 1
        mock_redis.hset.assert_called_once()

    def test_verify_checksums(self) -> None:
        """Verify reads back from Redis and compares."""
        from three_surgeons.core.migration import RedisMigrationDestination

        item = {"key": "k1", "value": "v1", "grade": "anecdotal"}
        expected_checksum = hashlib.sha256(
            json.dumps(item, sort_keys=True).encode()
        ).hexdigest()

        mock_redis = MagicMock()
        mock_redis.hget.return_value = json.dumps(item, sort_keys=True)
        dest = RedisMigrationDestination(client=mock_redis, key_prefix="3surgeons:evidence")
        assert dest.verify({"k1": expected_checksum}) is True

    def test_clear_deletes_prefix(self) -> None:
        """Clear removes all keys with the prefix."""
        from three_surgeons.core.migration import RedisMigrationDestination

        mock_redis = MagicMock()
        mock_redis.scan_iter.return_value = [
            "3surgeons:evidence:k1", "3surgeons:evidence:k2"
        ]
        dest = RedisMigrationDestination(client=mock_redis, key_prefix="3surgeons:evidence")
        dest.clear()
        assert mock_redis.delete.called


import sqlite3
from pathlib import Path
from three_surgeons.core.migration import EvidenceMigrator


class TestEvidenceMigratorWithDestination:
    def _create_evidence_db(self, db_path: Path) -> None:
        conn = sqlite3.connect(str(db_path))
        conn.execute("""
            CREATE TABLE IF NOT EXISTS learnings (
                id INTEGER PRIMARY KEY, key TEXT UNIQUE,
                value TEXT, grade TEXT DEFAULT 'anecdotal',
                observations INTEGER DEFAULT 1,
                created_at TEXT, updated_at TEXT
            )
        """)
        conn.execute(
            "INSERT INTO learnings (key, value, grade) VALUES (?, ?, ?)",
            ("learning-1", "Always use WAL mode", "case_series"),
        )
        conn.execute(
            "INSERT INTO learnings (key, value, grade) VALUES (?, ?, ?)",
            ("learning-2", "Restart after config", "anecdotal"),
        )
        conn.commit()
        conn.close()

    def test_migrate_to_destination(self, tmp_path: Path) -> None:
        """migrate() writes to destination and verifies round-trip."""
        db_path = tmp_path / "evidence.db"
        self._create_evidence_db(db_path)

        dest = MemoryMigrationDestination()
        migrator = EvidenceMigrator(source_db=db_path, destination=dest)
        result = migrator.migrate()

        assert result.executed is True
        assert result.migrated == 2
        assert len(dest.items) == 2

    def test_migrate_without_destination_still_works(self, tmp_path: Path) -> None:
        """Phase 1 behavior: migrate without destination = snapshot only."""
        db_path = tmp_path / "evidence.db"
        self._create_evidence_db(db_path)

        migrator = EvidenceMigrator(source_db=db_path)
        result = migrator.migrate()

        assert result.executed is True
        assert result.migrated == 2

    def test_migrate_verifies_roundtrip(self, tmp_path: Path) -> None:
        """Verification step confirms destination has correct data."""
        db_path = tmp_path / "evidence.db"
        self._create_evidence_db(db_path)

        dest = MemoryMigrationDestination()
        migrator = EvidenceMigrator(source_db=db_path, destination=dest)
        result = migrator.migrate()
        assert result.verified is True

    def test_dry_run_does_not_write(self, tmp_path: Path) -> None:
        """dry_run() never writes to destination."""
        db_path = tmp_path / "evidence.db"
        self._create_evidence_db(db_path)

        dest = MemoryMigrationDestination()
        migrator = EvidenceMigrator(source_db=db_path, destination=dest)
        result = migrator.dry_run()

        assert result.executed is False
        assert len(dest.items) == 0


class TestContextDNAMigrationDestination:
    def test_write_batch_posts_to_api(self) -> None:
        """ContextDNA destination POSTs to evidence API endpoint."""
        from three_surgeons.core.migration import ContextDNAMigrationDestination

        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"stored": 2}
        mock_client.post.return_value = mock_response

        dest = ContextDNAMigrationDestination(
            client=mock_client,
            evidence_endpoint="http://localhost:8029/api/evidence",
        )
        items = [
            {"key": "k1", "value": "v1", "grade": "anecdotal"},
            {"key": "k2", "value": "v2", "grade": "case_series"},
        ]
        count = dest.write_batch(items)
        assert count == 2
        mock_client.post.assert_called_once()

    def test_verify_fetches_and_compares(self) -> None:
        from three_surgeons.core.migration import ContextDNAMigrationDestination

        item = {"key": "k1", "value": "v1", "grade": "anecdotal"}
        expected = hashlib.sha256(json.dumps(item, sort_keys=True).encode()).hexdigest()

        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"items": [item]}
        mock_client.get.return_value = mock_response

        dest = ContextDNAMigrationDestination(
            client=mock_client,
            evidence_endpoint="http://localhost:8029/api/evidence",
        )
        assert dest.verify({"k1": expected}) is True

    def test_clear_calls_delete_endpoint(self) -> None:
        from three_surgeons.core.migration import ContextDNAMigrationDestination

        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_client.delete.return_value = mock_response

        dest = ContextDNAMigrationDestination(
            client=mock_client,
            evidence_endpoint="http://localhost:8029/api/evidence",
        )
        dest.clear()
        mock_client.delete.assert_called_once()
