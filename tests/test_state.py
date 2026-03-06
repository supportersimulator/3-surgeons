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


def test_create_backend_from_config_sqlite(tmp_path):
    from three_surgeons.core.config import StateConfig
    from three_surgeons.core.state import create_backend_from_config
    sc = StateConfig(backend="sqlite", sqlite_path=str(tmp_path / "test.db"))
    backend = create_backend_from_config(sc)
    assert backend.ping()


def test_create_backend_from_config_memory():
    from three_surgeons.core.config import StateConfig
    from three_surgeons.core.state import create_backend_from_config
    sc = StateConfig(backend="memory")
    backend = create_backend_from_config(sc)
    assert backend.ping()


def test_create_backend_from_config_unknown():
    import pytest
    from three_surgeons.core.config import StateConfig
    from three_surgeons.core.state import create_backend_from_config
    sc = StateConfig(backend="cassandra")
    with pytest.raises(ValueError, match="Unknown backend"):
        create_backend_from_config(sc)


# ── Sorted Set Tests ──────────────────────────────────────────────────


class TestSortedSetAdd:
    """Test sorted_set_add: adds member with score."""

    def test_add_single_member(self, backend: StateBackend) -> None:
        """Add one member, verify it's retrievable."""
        backend.sorted_set_add("zset", "item_a", 1.0)
        result = backend.sorted_set_range("zset", 0.0, float("inf"))
        assert result == [("item_a", 1.0)]

    def test_add_multiple_members_ordered_by_score(self, backend: StateBackend) -> None:
        """Add members out of order, verify returned sorted by score."""
        backend.sorted_set_add("zset", "high", 10.0)
        backend.sorted_set_add("zset", "low", 1.0)
        backend.sorted_set_add("zset", "mid", 5.0)
        result = backend.sorted_set_range("zset", 0.0, float("inf"))
        assert [m for m, s in result] == ["low", "mid", "high"]

    def test_add_updates_score_for_existing_member(self, backend: StateBackend) -> None:
        """Adding same member again updates its score."""
        backend.sorted_set_add("zset", "item", 1.0)
        backend.sorted_set_add("zset", "item", 99.0)
        result = backend.sorted_set_range("zset", 0.0, float("inf"))
        assert result == [("item", 99.0)]


class TestSortedSetRange:
    """Test sorted_set_range: retrieves members by score range."""

    def test_range_filters_by_score(self, backend: StateBackend) -> None:
        """Only members within [min_score, max_score] are returned."""
        backend.sorted_set_add("zset", "a", 1.0)
        backend.sorted_set_add("zset", "b", 5.0)
        backend.sorted_set_add("zset", "c", 10.0)
        result = backend.sorted_set_range("zset", 3.0, 7.0)
        assert result == [("b", 5.0)]

    def test_range_with_limit(self, backend: StateBackend) -> None:
        """Limit restricts number of results."""
        for i in range(10):
            backend.sorted_set_add("zset", f"item_{i}", float(i))
        result = backend.sorted_set_range("zset", 0.0, float("inf"), limit=3)
        assert len(result) == 3

    def test_range_empty_set_returns_empty(self, backend: StateBackend) -> None:
        """Range on non-existent key returns empty list."""
        result = backend.sorted_set_range("nokey", 0.0, float("inf"))
        assert result == []


class TestSortedSetRemove:
    """Test sorted_set_remove: removes a member by name."""

    def test_remove_existing_member(self, backend: StateBackend) -> None:
        """Remove a member, verify it's gone."""
        backend.sorted_set_add("zset", "a", 1.0)
        backend.sorted_set_add("zset", "b", 2.0)
        backend.sorted_set_remove("zset", "a")
        result = backend.sorted_set_range("zset", 0.0, float("inf"))
        assert result == [("b", 2.0)]

    def test_remove_nonexistent_member(self, backend: StateBackend) -> None:
        """Removing a member that doesn't exist should not raise."""
        backend.sorted_set_remove("zset", "ghost")  # Should not raise


class TestSortedSetCount:
    """Test sorted_set_count: returns number of members."""

    def test_count(self, backend: StateBackend) -> None:
        """Count returns number of members in sorted set."""
        backend.sorted_set_add("zset", "a", 1.0)
        backend.sorted_set_add("zset", "b", 2.0)
        assert backend.sorted_set_count("zset") == 2

    def test_count_empty(self, backend: StateBackend) -> None:
        """Count on non-existent key returns 0."""
        assert backend.sorted_set_count("nokey") == 0


# ── Hash Tests ────────────────────────────────────────────────────────


class TestHashSetGet:
    """Test hash_set and hash_get: field-level storage."""

    def test_set_and_get_field(self, backend: StateBackend) -> None:
        """Set a hash field and retrieve it."""
        backend.hash_set("myhash", "name", "atlas")
        assert backend.hash_get("myhash", "name") == "atlas"

    def test_get_missing_field_returns_none(self, backend: StateBackend) -> None:
        """Getting a non-existent field returns None."""
        assert backend.hash_get("myhash", "missing") is None

    def test_set_overwrites_field(self, backend: StateBackend) -> None:
        """Setting same field again overwrites."""
        backend.hash_set("myhash", "key", "first")
        backend.hash_set("myhash", "key", "second")
        assert backend.hash_get("myhash", "key") == "second"

    def test_separate_hash_keys(self, backend: StateBackend) -> None:
        """Different hash keys are independent."""
        backend.hash_set("hash1", "field", "val1")
        backend.hash_set("hash2", "field", "val2")
        assert backend.hash_get("hash1", "field") == "val1"
        assert backend.hash_get("hash2", "field") == "val2"


class TestHashGetAll:
    """Test hash_get_all: retrieves all fields."""

    def test_get_all_fields(self, backend: StateBackend) -> None:
        """Returns dict of all field-value pairs."""
        backend.hash_set("myhash", "a", "1")
        backend.hash_set("myhash", "b", "2")
        result = backend.hash_get_all("myhash")
        assert result == {"a": "1", "b": "2"}

    def test_get_all_empty_returns_empty_dict(self, backend: StateBackend) -> None:
        """hash_get_all on non-existent key returns empty dict."""
        result = backend.hash_get_all("nokey")
        assert result == {}


class TestHashDelete:
    """Test hash_delete: removes a field from a hash."""

    def test_delete_field(self, backend: StateBackend) -> None:
        """Delete a field, verify it's gone."""
        backend.hash_set("myhash", "a", "1")
        backend.hash_set("myhash", "b", "2")
        backend.hash_delete("myhash", "a")
        assert backend.hash_get("myhash", "a") is None
        assert backend.hash_get("myhash", "b") == "2"

    def test_delete_nonexistent_field(self, backend: StateBackend) -> None:
        """Deleting a field that doesn't exist should not raise."""
        backend.hash_delete("myhash", "ghost")  # Should not raise


class TestHashIncrement:
    """Test hash_increment: atomically increment a hash field."""

    def test_increment_new_field(self, backend: StateBackend) -> None:
        """Incrementing a non-existent field initializes to 1."""
        assert backend.hash_increment("myhash", "counter") == 1

    def test_increment_existing_field(self, backend: StateBackend) -> None:
        """Incrementing an existing numeric field adds 1."""
        backend.hash_set("myhash", "counter", "5")
        assert backend.hash_increment("myhash", "counter") == 6
        assert backend.hash_get("myhash", "counter") == "6"
