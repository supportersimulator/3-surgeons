"""Tests for the state backend abstraction layer."""
from __future__ import annotations

from pathlib import Path
from typing import Generator

import pytest

from three_surgeons.core.state import (
    MemoryBackend,
    SQLiteBackend,
    StateBackend,
    create_backend,
)


@pytest.fixture
def memory_backend() -> MemoryBackend:
    """Create a fresh MemoryBackend for each test."""
    return MemoryBackend()


@pytest.fixture
def sqlite_backend(tmp_path: Path) -> SQLiteBackend:
    """Create a fresh SQLiteBackend in a temp directory for each test."""
    db_path = str(tmp_path / "test_state.db")
    return SQLiteBackend(db_path=db_path)


@pytest.fixture(params=["memory", "sqlite"])
def backend(request: pytest.FixtureRequest, tmp_path: Path) -> StateBackend:
    """Parametrize tests to run against both MemoryBackend and SQLiteBackend."""
    if request.param == "memory":
        return MemoryBackend()
    else:
        db_path = str(tmp_path / "test_state.db")
        return SQLiteBackend(db_path=db_path)


class TestGetSet:
    """Test basic get/set operations."""

    def test_get_set(self, backend: StateBackend) -> None:
        """Set a value and retrieve it."""
        backend.set("greeting", "hello")
        assert backend.get("greeting") == "hello"

    def test_get_missing_returns_none(self, backend: StateBackend) -> None:
        """Getting a non-existent key returns None."""
        assert backend.get("nonexistent") is None

    def test_set_overwrites(self, backend: StateBackend) -> None:
        """Setting the same key again overwrites the previous value."""
        backend.set("key", "first")
        backend.set("key", "second")
        assert backend.get("key") == "second"


class TestTTL:
    """Test TTL (time-to-live) support."""

    def test_set_with_ttl(self, backend: StateBackend) -> None:
        """Set a key with a TTL, retrieve immediately — should succeed."""
        backend.set("temp", "value", ttl=60)
        assert backend.get("temp") == "value"

    def test_expired_key_returns_none(self, backend: StateBackend) -> None:
        """Set a key with TTL=0 (already expired), should return None on get."""
        backend.set("temp", "value", ttl=-1)
        assert backend.get("temp") is None


class TestDelete:
    """Test delete operations."""

    def test_delete(self, backend: StateBackend) -> None:
        """Delete an existing key, verify it's gone."""
        backend.set("doomed", "value")
        backend.delete("doomed")
        assert backend.get("doomed") is None

    def test_delete_nonexistent(self, backend: StateBackend) -> None:
        """Deleting a key that doesn't exist should not raise."""
        backend.delete("ghost")  # Should not raise


class TestIncrement:
    """Test atomic increment operations."""

    def test_increment(self, backend: StateBackend) -> None:
        """Increment a key twice, verify values are 1 then 2."""
        assert backend.increment("counter") == 1
        assert backend.increment("counter") == 2

    def test_increment_with_ttl(self, backend: StateBackend) -> None:
        """Increment with TTL, verify value persists immediately."""
        assert backend.increment("counter", ttl=60) == 1
        assert backend.get("counter") == "1"


class TestLists:
    """Test list push, range, and trim operations."""

    def test_list_push_and_range(self, backend: StateBackend) -> None:
        """Push a, b — range returns [b, a] (prepend order like LPUSH)."""
        backend.list_push("mylist", "a")
        backend.list_push("mylist", "b")
        result = backend.list_range("mylist", 0, -1)
        assert result == ["b", "a"]

    def test_list_range_subset(self, backend: StateBackend) -> None:
        """Push a, b, c — range(0, 1) returns [c, b] (first two)."""
        backend.list_push("mylist", "a")
        backend.list_push("mylist", "b")
        backend.list_push("mylist", "c")
        result = backend.list_range("mylist", 0, 1)
        assert result == ["c", "b"]

    def test_list_range_empty(self, backend: StateBackend) -> None:
        """Range on non-existent list returns empty list."""
        result = backend.list_range("nolist", 0, -1)
        assert result == []

    def test_list_trim(self, backend: StateBackend) -> None:
        """Push 10 items, trim to keep first 5, verify length is 5."""
        for i in range(10):
            backend.list_push("mylist", str(i))
        backend.list_trim("mylist", 0, 4)
        result = backend.list_range("mylist", 0, -1)
        assert len(result) == 5


class TestLock:
    """Test lock acquire/release operations."""

    def test_acquire_and_release_lock(self, backend: StateBackend) -> None:
        """Acquire a lock, verify it's held, release it."""
        assert backend.acquire_lock("mylock", ttl=60) is True
        # Acquiring the same lock again should fail (it's held)
        assert backend.acquire_lock("mylock", ttl=60) is False
        backend.release_lock("mylock")
        # Now it should be acquirable again
        assert backend.acquire_lock("mylock", ttl=60) is True

    def test_release_unheld_lock(self, backend: StateBackend) -> None:
        """Releasing a lock that isn't held should not raise."""
        backend.release_lock("nolock")  # Should not raise


class TestPing:
    """Test the ping health check."""

    def test_ping(self, backend: StateBackend) -> None:
        """Ping should return True for both backends."""
        assert backend.ping() is True


class TestFactory:
    """Test the create_backend factory function."""

    def test_create_memory_backend(self) -> None:
        """Factory creates MemoryBackend for 'memory' type."""
        b = create_backend("memory")
        assert isinstance(b, MemoryBackend)

    def test_create_sqlite_backend(self, tmp_path: Path) -> None:
        """Factory creates SQLiteBackend for 'sqlite' type."""
        db_path = str(tmp_path / "factory.db")
        b = create_backend("sqlite", db_path=db_path)
        assert isinstance(b, SQLiteBackend)

    def test_create_default_is_memory(self) -> None:
        """Factory with no arguments creates MemoryBackend."""
        b = create_backend()
        assert isinstance(b, MemoryBackend)

    def test_create_unknown_type_raises(self) -> None:
        """Factory with unknown type raises ValueError."""
        with pytest.raises(ValueError, match="Unknown backend"):
            create_backend("cassandra")
