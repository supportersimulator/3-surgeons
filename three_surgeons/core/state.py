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
