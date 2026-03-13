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
