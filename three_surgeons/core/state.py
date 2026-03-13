"""State backend abstraction with Memory, SQLite, and Redis implementations.

Provides a unified interface for key-value storage, lists, locks, and TTL
support. Three backends:
- MemoryBackend: in-memory, for testing
- SQLiteBackend: file-based, portable
- _RedisBackend: full-featured, requires redis package
"""
from __future__ import annotations

import sqlite3
import threading
import time
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Dict, List, Optional, Tuple


class StateBackend(ABC):
    """Abstract base class for state storage backends."""

    @abstractmethod
    def get(self, key: str) -> Optional[str]:
        """Get value by key. Returns None if missing or expired."""

    @abstractmethod
    def set(self, key: str, value: str, ttl: Optional[int] = None) -> None:
        """Set key to value. Optional TTL in seconds."""

    @abstractmethod
    def delete(self, key: str) -> None:
        """Delete a key. No-op if missing."""

    @abstractmethod
    def increment(self, key: str, ttl: Optional[int] = None) -> int:
        """Atomically increment key by 1. Initializes to 0 if missing. Returns new value."""

    @abstractmethod
    def list_push(self, key: str, value: str) -> None:
        """Prepend value to list (like Redis LPUSH)."""

    @abstractmethod
    def list_range(self, key: str, start: int, stop: int) -> List[str]:
        """Return list elements from start to stop. stop=-1 means all remaining."""

    @abstractmethod
    def list_trim(self, key: str, start: int, stop: int) -> None:
        """Keep only elements from start to stop (inclusive)."""

    @abstractmethod
    def acquire_lock(self, name: str, ttl: int = 60) -> bool:
        """Try to acquire a named lock. Returns True if acquired."""

    @abstractmethod
    def release_lock(self, name: str) -> None:
        """Release a named lock. No-op if not held."""

    # ── Sorted Sets ──────────────────────────────────────────────────

    @abstractmethod
    def sorted_set_add(self, key: str, member: str, score: float) -> None:
        """Add member with score (like Redis ZADD). Updates score if member exists."""

    @abstractmethod
    def sorted_set_range(
        self, key: str, min_score: float, max_score: float, limit: int = 0
    ) -> List[Tuple[str, float]]:
        """Return members with scores in [min_score, max_score], ordered by score.

        limit=0 means no limit. Returns list of (member, score) tuples.
        """

    @abstractmethod
    def sorted_set_remove(self, key: str, member: str) -> None:
        """Remove member from sorted set. No-op if missing."""

    @abstractmethod
    def sorted_set_count(self, key: str) -> int:
        """Return number of members in sorted set."""

    # ── Hashes ────────────────────────────────────────────────────────

    @abstractmethod
    def hash_set(self, key: str, field: str, value: str) -> None:
        """Set field in hash (like Redis HSET)."""

    @abstractmethod
    def hash_get(self, key: str, field: str) -> Optional[str]:
        """Get field from hash. Returns None if missing."""

    @abstractmethod
    def hash_get_all(self, key: str) -> Dict[str, str]:
        """Get all fields from hash. Returns empty dict if missing."""

    @abstractmethod
    def hash_delete(self, key: str, field: str) -> None:
        """Delete field from hash. No-op if missing."""

    @abstractmethod
    def hash_increment(self, key: str, field: str, amount: int = 1) -> int:
        """Atomically increment hash field. Initializes to 0 if missing. Returns new value."""

    @abstractmethod
    def ping(self) -> bool:
        """Health check. Returns True if backend is operational."""


class MemoryBackend(StateBackend):
    """In-memory state backend for testing.

    Uses dicts for kv store and lists. TTL via (value, expires_at) tuples.
    Thread-safe locks via threading.Lock().
    """

    def __init__(self) -> None:
        self._kv: Dict[str, Tuple[str, Optional[float]]] = {}
        self._lists: Dict[str, List[str]] = {}
        self._sorted_sets: Dict[str, Dict[str, float]] = {}
        self._hashes: Dict[str, Dict[str, str]] = {}
        self._locks: Dict[str, float] = {}
        self._mutex = threading.Lock()

    def get(self, key: str) -> Optional[str]:
        entry = self._kv.get(key)
        if entry is None:
            return None
        value, expires_at = entry
        if expires_at is not None and time.time() >= expires_at:
            del self._kv[key]
            return None
        return value

    def set(self, key: str, value: str, ttl: Optional[int] = None) -> None:
        expires_at: Optional[float] = None
        if ttl is not None:
            expires_at = time.time() + ttl
        self._kv[key] = (value, expires_at)

    def delete(self, key: str) -> None:
        self._kv.pop(key, None)

    def increment(self, key: str, ttl: Optional[int] = None) -> int:
        current = self.get(key)
        new_val = int(current) + 1 if current is not None else 1
        self.set(key, str(new_val), ttl=ttl)
        return new_val

    def list_push(self, key: str, value: str) -> None:
        if key not in self._lists:
            self._lists[key] = []
        self._lists[key].insert(0, value)

    def list_range(self, key: str, start: int, stop: int) -> List[str]:
        lst = self._lists.get(key, [])
        if not lst:
            return []
        if stop == -1:
            return lst[start:]
        return lst[start : stop + 1]

    def list_trim(self, key: str, start: int, stop: int) -> None:
        lst = self._lists.get(key)
        if lst is None:
            return
        if stop == -1:
            self._lists[key] = lst[start:]
        else:
            self._lists[key] = lst[start : stop + 1]

    def sorted_set_add(self, key: str, member: str, score: float) -> None:
        if key not in self._sorted_sets:
            self._sorted_sets[key] = {}
        self._sorted_sets[key][member] = score

    def sorted_set_range(
        self, key: str, min_score: float, max_score: float, limit: int = 0
    ) -> List[Tuple[str, float]]:
        ss = self._sorted_sets.get(key, {})
        items = sorted(
            ((m, s) for m, s in ss.items() if min_score <= s <= max_score),
            key=lambda x: x[1],
        )
        if limit > 0:
            items = items[:limit]
        return items

    def sorted_set_remove(self, key: str, member: str) -> None:
        if key in self._sorted_sets:
            self._sorted_sets[key].pop(member, None)

    def sorted_set_count(self, key: str) -> int:
        return len(self._sorted_sets.get(key, {}))

    def hash_set(self, key: str, field: str, value: str) -> None:
        if key not in self._hashes:
            self._hashes[key] = {}
        self._hashes[key][field] = value

    def hash_get(self, key: str, field: str) -> Optional[str]:
        return self._hashes.get(key, {}).get(field)

    def hash_get_all(self, key: str) -> Dict[str, str]:
        return dict(self._hashes.get(key, {}))

    def hash_delete(self, key: str, field: str) -> None:
        if key in self._hashes:
            self._hashes[key].pop(field, None)

    def hash_increment(self, key: str, field: str, amount: int = 1) -> int:
        current = self.hash_get(key, field)
        new_val = int(current) + amount if current is not None else amount
        self.hash_set(key, field, str(new_val))
        return new_val

    def acquire_lock(self, name: str, ttl: int = 60) -> bool:
        with self._mutex:
            now = time.time()
            if name in self._locks and self._locks[name] > now:
                return False
            self._locks[name] = now + ttl
            return True

    def release_lock(self, name: str) -> None:
        with self._mutex:
            self._locks.pop(name, None)

    def ping(self) -> bool:
        return True


class SQLiteBackend(StateBackend):
    """SQLite-based state backend for portable persistence.

    Uses WAL mode for concurrent read access. Tables:
    - kv: key-value store with optional TTL
    - lists: ordered lists with index-based access
    """

    def __init__(self, db_path: str) -> None:
        path = Path(db_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        self._db_path = db_path
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._db_path)
        conn.execute("PRAGMA journal_mode=WAL")
        return conn

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.execute(
                "CREATE TABLE IF NOT EXISTS kv ("
                "  key TEXT PRIMARY KEY,"
                "  value TEXT,"
                "  expires_at REAL"
                ")"
            )
            conn.execute(
                "CREATE TABLE IF NOT EXISTS lists ("
                "  key TEXT,"
                "  idx INTEGER,"
                "  value TEXT"
                ")"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS ix_lists_key ON lists(key, idx)"
            )
            conn.execute(
                "CREATE TABLE IF NOT EXISTS sorted_sets ("
                "  key TEXT,"
                "  member TEXT,"
                "  score REAL,"
                "  PRIMARY KEY (key, member)"
                ")"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS ix_sorted_sets_score "
                "ON sorted_sets(key, score)"
            )
            conn.execute(
                "CREATE TABLE IF NOT EXISTS hashes ("
                "  key TEXT,"
                "  field TEXT,"
                "  value TEXT,"
                "  PRIMARY KEY (key, field)"
                ")"
            )
            conn.commit()

    def get(self, key: str) -> Optional[str]:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT value, expires_at FROM kv WHERE key = ?", (key,)
            ).fetchone()
        if row is None:
            return None
        value, expires_at = row
        if expires_at is not None and time.time() >= expires_at:
            self.delete(key)
            return None
        return value

    def set(self, key: str, value: str, ttl: Optional[int] = None) -> None:
        expires_at: Optional[float] = None
        if ttl is not None:
            expires_at = time.time() + ttl
        with self._connect() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO kv (key, value, expires_at) VALUES (?, ?, ?)",
                (key, value, expires_at),
            )
            conn.commit()

    def delete(self, key: str) -> None:
        with self._connect() as conn:
            conn.execute("DELETE FROM kv WHERE key = ?", (key,))
            conn.commit()

    def increment(self, key: str, ttl: Optional[int] = None) -> int:
        current = self.get(key)
        new_val = int(current) + 1 if current is not None else 1
        self.set(key, str(new_val), ttl=ttl)
        return new_val

    def list_push(self, key: str, value: str) -> None:
        with self._connect() as conn:
            # Shift all existing indices up by 1
            conn.execute(
                "UPDATE lists SET idx = idx + 1 WHERE key = ?", (key,)
            )
            # Insert new element at index 0
            conn.execute(
                "INSERT INTO lists (key, idx, value) VALUES (?, 0, ?)",
                (key, value),
            )
            conn.commit()

    def list_range(self, key: str, start: int, stop: int) -> List[str]:
        with self._connect() as conn:
            if stop == -1:
                rows = conn.execute(
                    "SELECT value FROM lists WHERE key = ? AND idx >= ? ORDER BY idx",
                    (key, start),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT value FROM lists WHERE key = ? AND idx >= ? AND idx <= ? ORDER BY idx",
                    (key, start, stop),
                ).fetchall()
        return [r[0] for r in rows]

    def list_trim(self, key: str, start: int, stop: int) -> None:
        with self._connect() as conn:
            if stop == -1:
                conn.execute(
                    "DELETE FROM lists WHERE key = ? AND idx < ?",
                    (key, start),
                )
            else:
                conn.execute(
                    "DELETE FROM lists WHERE key = ? AND (idx < ? OR idx > ?)",
                    (key, start, stop),
                )
            conn.commit()

    def sorted_set_add(self, key: str, member: str, score: float) -> None:
        with self._connect() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO sorted_sets (key, member, score) VALUES (?, ?, ?)",
                (key, member, score),
            )
            conn.commit()

    def sorted_set_range(
        self, key: str, min_score: float, max_score: float, limit: int = 0
    ) -> List[Tuple[str, float]]:
        with self._connect() as conn:
            query = "SELECT member, score FROM sorted_sets WHERE key = ? AND score >= ? AND score <= ? ORDER BY score"
            params: list = [key, min_score, max_score]
            if limit > 0:
                query += " LIMIT ?"
                params.append(limit)
            rows = conn.execute(query, params).fetchall()
        return [(r[0], r[1]) for r in rows]

    def sorted_set_remove(self, key: str, member: str) -> None:
        with self._connect() as conn:
            conn.execute(
                "DELETE FROM sorted_sets WHERE key = ? AND member = ?",
                (key, member),
            )
            conn.commit()

    def sorted_set_count(self, key: str) -> int:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT COUNT(*) FROM sorted_sets WHERE key = ?", (key,)
            ).fetchone()
        return row[0] if row else 0

    def hash_set(self, key: str, field: str, value: str) -> None:
        with self._connect() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO hashes (key, field, value) VALUES (?, ?, ?)",
                (key, field, value),
            )
            conn.commit()

    def hash_get(self, key: str, field: str) -> Optional[str]:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT value FROM hashes WHERE key = ? AND field = ?",
                (key, field),
            ).fetchone()
        return row[0] if row else None

    def hash_get_all(self, key: str) -> Dict[str, str]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT field, value FROM hashes WHERE key = ?", (key,)
            ).fetchall()
        return {r[0]: r[1] for r in rows}

    def hash_delete(self, key: str, field: str) -> None:
        with self._connect() as conn:
            conn.execute(
                "DELETE FROM hashes WHERE key = ? AND field = ?",
                (key, field),
            )
            conn.commit()

    def hash_increment(self, key: str, field: str, amount: int = 1) -> int:
        with self._connect() as conn:
            # Atomic: INSERT default 0 if missing, then UPDATE in one transaction
            conn.execute(
                "INSERT OR IGNORE INTO hashes (key, field, value) VALUES (?, ?, '0')",
                (key, field),
            )
            conn.execute(
                "UPDATE hashes SET value = CAST(CAST(value AS INTEGER) + ? AS TEXT) "
                "WHERE key = ? AND field = ?",
                (amount, key, field),
            )
            conn.commit()
            row = conn.execute(
                "SELECT value FROM hashes WHERE key = ? AND field = ?",
                (key, field),
            ).fetchone()
        return int(row[0])

    def acquire_lock(self, name: str, ttl: int = 60) -> bool:
        lock_key = f"_lock:{name}"
        now = time.time()
        # Check if lock exists and is not expired
        current = self.get(lock_key)
        if current is not None:
            return False
        self.set(lock_key, str(now), ttl=ttl)
        return True

    def release_lock(self, name: str) -> None:
        lock_key = f"_lock:{name}"
        self.delete(lock_key)

    def ping(self) -> bool:
        try:
            with self._connect() as conn:
                conn.execute("SELECT 1")
            return True
        except Exception:
            return False


class _RedisBackend(StateBackend):
    """Redis-based state backend for full-featured distributed state.

    Wraps redis.Redis client. Requires the 'redis' optional dependency.
    """

    def __init__(self, url: str = "redis://localhost:6379/0") -> None:
        import redis

        self._client = redis.Redis.from_url(url, decode_responses=True)

    def get(self, key: str) -> Optional[str]:
        return self._client.get(key)

    def set(self, key: str, value: str, ttl: Optional[int] = None) -> None:
        if ttl is not None:
            self._client.setex(key, ttl, value)
        else:
            self._client.set(key, value)

    def delete(self, key: str) -> None:
        self._client.delete(key)

    def increment(self, key: str, ttl: Optional[int] = None) -> int:
        val = self._client.incr(key)
        if ttl is not None:
            self._client.expire(key, ttl)
        return val

    def list_push(self, key: str, value: str) -> None:
        self._client.lpush(key, value)

    def list_range(self, key: str, start: int, stop: int) -> List[str]:
        return self._client.lrange(key, start, stop)

    def list_trim(self, key: str, start: int, stop: int) -> None:
        self._client.ltrim(key, start, stop)

    def sorted_set_add(self, key: str, member: str, score: float) -> None:
        self._client.zadd(key, {member: score})

    def sorted_set_range(
        self, key: str, min_score: float, max_score: float, limit: int = 0
    ) -> List[Tuple[str, float]]:
        if limit > 0:
            results = self._client.zrangebyscore(
                key, min_score, max_score, start=0, num=limit, withscores=True
            )
        else:
            results = self._client.zrangebyscore(
                key, min_score, max_score, withscores=True
            )
        return [(m, s) for m, s in results]

    def sorted_set_remove(self, key: str, member: str) -> None:
        self._client.zrem(key, member)

    def sorted_set_count(self, key: str) -> int:
        return self._client.zcard(key)

    def hash_set(self, key: str, field: str, value: str) -> None:
        self._client.hset(key, field, value)

    def hash_get(self, key: str, field: str) -> Optional[str]:
        return self._client.hget(key, field)

    def hash_get_all(self, key: str) -> Dict[str, str]:
        return self._client.hgetall(key)

    def hash_delete(self, key: str, field: str) -> None:
        self._client.hdel(key, field)

    def hash_increment(self, key: str, field: str, amount: int = 1) -> int:
        return self._client.hincrby(key, field, amount)

    def acquire_lock(self, name: str, ttl: int = 60) -> bool:
        return bool(self._client.set(f"_lock:{name}", "1", nx=True, ex=ttl))

    def release_lock(self, name: str) -> None:
        self._client.delete(f"_lock:{name}")

    def ping(self) -> bool:
        try:
            return self._client.ping()
        except Exception:
            return False


def create_backend(backend_type: str = "memory", **kwargs: str) -> StateBackend:
    """Factory function to create a state backend.

    Args:
        backend_type: One of "memory", "sqlite", "redis".
        **kwargs: Backend-specific arguments.
            - sqlite: db_path (str)
            - redis: url (str)

    Returns:
        A StateBackend instance.

    Raises:
        ValueError: If backend_type is unknown.
    """
    if backend_type == "memory":
        return MemoryBackend()
    elif backend_type == "sqlite":
        return SQLiteBackend(db_path=kwargs["db_path"])
    elif backend_type == "redis":
        try:
            return _RedisBackend(url=kwargs.get("url", "redis://localhost:6379/0"))
        except ImportError:
            # Fall back to SQLite if redis package not available
            return SQLiteBackend(db_path=kwargs.get("db_path", "~/.3surgeons/state.db"))
    else:
        raise ValueError(f"Unknown backend type: {backend_type!r}")


def create_backend_from_config(state_config: "StateConfig") -> StateBackend:
    """Create a state backend from a StateConfig object.

    Uses the StateConfig's backend field to determine which backend to create.
    Falls back to SQLite if Redis package is not installed.
    """
    from three_surgeons.core.config import StateConfig  # avoid circular import

    backend = state_config.backend
    if backend == "memory":
        return MemoryBackend()
    elif backend == "sqlite":
        path = str(state_config.resolved_sqlite_path)
        return SQLiteBackend(db_path=path)
    elif backend == "redis":
        try:
            return _RedisBackend(url=state_config.redis_url)
        except ImportError:
            path = str(state_config.resolved_sqlite_path)
            return SQLiteBackend(db_path=path)
    else:
        raise ValueError(f"Unknown backend: {backend!r}")


def resolve_state_backend(
    config_resolver: "ConfigResolver",
    sqlite_fallback_path: str = "~/.3-surgeons/state.db",
) -> StateBackend:
    """Create a StateBackend from a ConfigResolver's resolved state config.

    This is the Phase 2 entry point: config cascade → backend instance.
    Falls back to SQLite if Redis is unavailable.
    """
    from three_surgeons.core.config_resolver import ConfigResolver  # avoid circular

    state_config = config_resolver.resolve_state()
    backend_type = state_config.backend

    if backend_type == "memory":
        return MemoryBackend()
    elif backend_type == "redis":
        try:
            backend = _RedisBackend(url=state_config.redis_url)
            if backend.ping():
                return backend
            # Redis not responding — fall back
            return SQLiteBackend(db_path=sqlite_fallback_path)
        except Exception:
            return SQLiteBackend(db_path=sqlite_fallback_path)
    else:
        path = state_config.sqlite_path
        if path.startswith("~"):
            path = str(Path(path).expanduser())
        return SQLiteBackend(db_path=path)
