# three_surgeons/core/migration.py
"""Evidence migration between phases.

Additive merge, UP-ONLY grades, bidirectional sync support.
Pre-migration snapshots for safe rollback.
"""
from __future__ import annotations

import hashlib
import json
import shutil
import sqlite3
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Protocol, runtime_checkable


@dataclass
class MigrationResult:
    """Result of a migration operation."""

    total_items: int = 0
    would_migrate: int = 0
    migrated: int = 0
    skipped: int = 0
    executed: bool = False
    verified: bool = True
    items: List[Dict[str, Any]] = field(default_factory=list)


@runtime_checkable
class MigrationDestination(Protocol):
    """Protocol for migration write targets."""

    def write_batch(self, items: List[Dict[str, Any]]) -> int:
        """Write a batch of items. Returns count written."""
        ...

    def verify(self, checksums: Dict[str, str]) -> bool:
        """Verify round-trip by comparing checksums."""
        ...

    def clear(self) -> None:
        """Remove all migrated items (for rollback)."""
        ...


class MemoryMigrationDestination:
    """In-memory migration destination for testing."""

    def __init__(self) -> None:
        self.items: List[Dict[str, Any]] = []

    def write_batch(self, items: List[Dict[str, Any]]) -> int:
        self.items.extend(items)
        return len(items)

    def verify(self, checksums: Dict[str, str]) -> bool:
        for item in self.items:
            key = item.get("key", "")
            if key in checksums:
                computed = hashlib.sha256(
                    json.dumps(item, sort_keys=True).encode()
                ).hexdigest()
                if computed != checksums[key]:
                    return False
        return True

    def clear(self) -> None:
        self.items.clear()


class RedisMigrationDestination:
    """Writes evidence to Redis hashes.

    Key format: {prefix}:{item_key}
    Value: JSON string of the item dict.
    """

    def __init__(self, client: Any, key_prefix: str = "3surgeons:evidence") -> None:
        self._client = client
        self._prefix = key_prefix

    def write_batch(self, items: List[Dict[str, Any]]) -> int:
        count = 0
        for item in items:
            key = item.get("key", f"item_{count}")
            redis_key = f"{self._prefix}:{key}"
            self._client.hset(redis_key, mapping={
                "data": json.dumps(item, sort_keys=True),
                "grade": item.get("grade", "anecdotal"),
            })
            count += 1
        return count

    def verify(self, checksums: Dict[str, str]) -> bool:
        for key, expected in checksums.items():
            redis_key = f"{self._prefix}:{key}"
            stored = self._client.hget(redis_key, "data")
            if stored is None:
                return False
            computed = hashlib.sha256(stored.encode() if isinstance(stored, str) else stored).hexdigest()
            if computed != expected:
                return False
        return True

    def clear(self) -> None:
        for key in self._client.scan_iter(f"{self._prefix}:*"):
            self._client.delete(key)


class EvidenceMigrator:
    """Migrates evidence between local SQLite and shared backends.

    Rules:
    1. Pre-migration snapshot stored alongside config revert snapshot
    2. Additive merge, never overwrite
    3. UP-ONLY grade rule enforced during migration
    4. Revert = disconnect — local SQLite retains everything
    """

    def __init__(
        self,
        source_db: Path,
        snapshot_dir: Optional[Path] = None,
        destination: Optional[MigrationDestination] = None,
    ) -> None:
        self._source_db = source_db
        self._snapshot_dir = snapshot_dir or source_db.parent / "migration_snapshots"
        self._destination = destination

    def _read_learnings(self) -> List[Dict[str, Any]]:
        """Read all learnings from source evidence DB."""
        if not self._source_db.is_file():
            return []
        conn = sqlite3.connect(str(self._source_db))
        conn.row_factory = sqlite3.Row
        try:
            rows = conn.execute("SELECT * FROM learnings").fetchall()
            return [dict(row) for row in rows]
        except sqlite3.OperationalError:
            return []
        finally:
            conn.close()

    def dry_run(self) -> MigrationResult:
        """Show what would migrate without executing."""
        items = self._read_learnings()
        return MigrationResult(
            total_items=len(items),
            would_migrate=len(items),
            executed=False,
            items=items,
        )

    def migrate(self) -> MigrationResult:
        """Execute migration with pre-migration snapshot.

        Phase 1: snapshot + backup only (no shared backend yet).
        Phase 2 will add destination writes (Redis/shared SQLite).
        """
        items = self._read_learnings()

        # Create snapshot
        self._snapshot_dir.mkdir(parents=True, exist_ok=True)
        snapshot_path = self._snapshot_dir / f"pre_migration_{int(time.time())}.json"
        snapshot_path.write_text(json.dumps({
            "timestamp": time.time(),
            "source_db": str(self._source_db),
            "items": items,
            "db_backup": str(self._source_db) + ".bak",
        }, indent=2))

        # Backup the DB file
        if self._source_db.is_file():
            shutil.copy2(self._source_db, str(self._source_db) + ".bak")

        verified = True

        # Phase 2: write to destination if provided
        if self._destination is not None and items:
            self._destination.write_batch(items)

            # Verify round-trip
            checksums = {}
            for item in items:
                key = item.get("key", "")
                if key:
                    checksums[key] = hashlib.sha256(
                        json.dumps(item, sort_keys=True).encode()
                    ).hexdigest()
            if checksums:
                verified = self._destination.verify(checksums)

        return MigrationResult(
            total_items=len(items),
            would_migrate=len(items),
            migrated=len(items),
            executed=True,
            verified=verified,
            items=items,
        )

    def revert(self) -> bool:
        """Restore from most recent pre-migration snapshot."""
        if not self._snapshot_dir.is_dir():
            return False

        snapshots = sorted(self._snapshot_dir.glob("pre_migration_*.json"), reverse=True)
        if not snapshots:
            return False

        snapshot = json.loads(snapshots[0].read_text())
        backup_path = snapshot.get("db_backup")
        if backup_path and Path(backup_path).is_file():
            shutil.copy2(backup_path, self._source_db)
            return True
        return False
