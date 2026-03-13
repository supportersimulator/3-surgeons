# tests/test_lock_backend.py
"""Tests for the LockBackend protocol and FileLockBackend adapter."""
from __future__ import annotations

from pathlib import Path
from typing import Optional, Tuple

import pytest

from three_surgeons.core.priority_queue import LockBackend, FileLockBackend


class TestFileLockBackend:
    def test_acquire_and_release(self, tmp_path: Path) -> None:
        lock = FileLockBackend(lock_dir=tmp_path)
        assert lock.acquire(priority=4, caller="test", timeout=1.0) is True
        lock.release(caller="test")

    def test_is_locked(self, tmp_path: Path) -> None:
        lock = FileLockBackend(lock_dir=tmp_path)
        locked, _ = lock.is_locked()
        assert locked is False
        lock.acquire(priority=4, caller="worker", timeout=1.0)
        locked, holder = lock.is_locked()
        assert locked is True
        assert holder is not None
        lock.release(caller="worker")

    def test_health_check(self, tmp_path: Path) -> None:
        lock = FileLockBackend(lock_dir=tmp_path)
        assert lock.health_check() is True

    def test_isinstance_check(self, tmp_path: Path) -> None:
        lock = FileLockBackend(lock_dir=tmp_path)
        assert isinstance(lock, LockBackend)

    def test_renew_extends(self, tmp_path: Path) -> None:
        lock = FileLockBackend(lock_dir=tmp_path)
        lock.acquire(priority=4, caller="test", timeout=1.0)
        assert lock.renew(caller="test", extend_s=10.0) is True
        lock.release(caller="test")

    def test_double_release_safe(self, tmp_path: Path) -> None:
        lock = FileLockBackend(lock_dir=tmp_path)
        lock.acquire(priority=4, caller="test", timeout=1.0)
        lock.release(caller="test")
        lock.release(caller="test")  # Should not raise


from unittest.mock import MagicMock


class TestRedisLockBackend:
    def test_acquire_uses_setnx(self) -> None:
        """RedisLockBackend uses SET NX with TTL."""
        from three_surgeons.core.priority_queue import RedisLockBackend

        mock_redis = MagicMock()
        mock_redis.set.return_value = True
        lock = RedisLockBackend(client=mock_redis, key_prefix="3surgeons:gpu_lock")
        result = lock.acquire(priority=4, caller="test_worker", timeout=5.0)
        assert result is True
        mock_redis.set.assert_called_once()
        call_kwargs = mock_redis.set.call_args
        assert call_kwargs[1].get("nx") is True
        assert call_kwargs[1].get("ex") is not None

    def test_release_deletes_key(self) -> None:
        from three_surgeons.core.priority_queue import RedisLockBackend

        mock_redis = MagicMock()
        mock_redis.set.return_value = True
        lock = RedisLockBackend(client=mock_redis)
        lock.acquire(priority=4, caller="test", timeout=1.0)
        lock.release(caller="test")
        # Deletes both the lock key and the urgent key
        assert mock_redis.delete.call_count == 2

    def test_is_locked_reads_key(self) -> None:
        from three_surgeons.core.priority_queue import RedisLockBackend

        mock_redis = MagicMock()
        mock_redis.get.return_value = '{"pid": 12345, "caller": "worker"}'
        lock = RedisLockBackend(client=mock_redis)
        locked, holder = lock.is_locked()
        assert locked is True
        assert "12345" in (holder or "")

    def test_health_check_pings_redis(self) -> None:
        from three_surgeons.core.priority_queue import RedisLockBackend

        mock_redis = MagicMock()
        mock_redis.ping.return_value = True
        lock = RedisLockBackend(client=mock_redis)
        assert lock.health_check() is True

    def test_renew_extends_ttl(self) -> None:
        from three_surgeons.core.priority_queue import RedisLockBackend

        mock_redis = MagicMock()
        mock_redis.set.return_value = True
        mock_redis.expire.return_value = True
        lock = RedisLockBackend(client=mock_redis)
        lock.acquire(priority=4, caller="test", timeout=1.0)
        assert lock.renew(caller="test", extend_s=10.0) is True
        mock_redis.expire.assert_called_once()

    def test_isinstance_check(self) -> None:
        from three_surgeons.core.priority_queue import RedisLockBackend

        mock_redis = MagicMock()
        lock = RedisLockBackend(client=mock_redis)
        assert isinstance(lock, LockBackend)
