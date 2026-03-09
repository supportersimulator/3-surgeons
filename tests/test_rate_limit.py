"""Tests for strategy-pattern rate limiter."""
import time

import pytest


class TestMemoryRateLimiter:
    def test_allows_within_limit(self):
        from three_surgeons.http.rate_limit import MemoryRateLimiter
        rl = MemoryRateLimiter(max_calls=5, window_s=60.0)
        for _ in range(5):
            assert rl.allow("tool_a") is True

    def test_blocks_over_limit(self):
        from three_surgeons.http.rate_limit import MemoryRateLimiter
        rl = MemoryRateLimiter(max_calls=2, window_s=60.0)
        assert rl.allow("t") is True
        assert rl.allow("t") is True
        assert rl.allow("t") is False

    def test_separate_keys(self):
        from three_surgeons.http.rate_limit import MemoryRateLimiter
        rl = MemoryRateLimiter(max_calls=1, window_s=60.0)
        assert rl.allow("a") is True
        assert rl.allow("b") is True
        assert rl.allow("a") is False

    def test_window_expiry(self):
        from three_surgeons.http.rate_limit import MemoryRateLimiter
        rl = MemoryRateLimiter(max_calls=1, window_s=0.1)
        assert rl.allow("t") is True
        assert rl.allow("t") is False
        time.sleep(0.15)
        assert rl.allow("t") is True


class TestRateLimiterProtocol:
    """Both backends satisfy the same interface."""

    def test_memory_has_allow(self):
        from three_surgeons.http.rate_limit import MemoryRateLimiter, RateLimiterLike
        rl = MemoryRateLimiter()
        assert hasattr(rl, "allow")

    def test_redis_has_allow(self):
        from three_surgeons.http.rate_limit import RedisRateLimiter
        # Instantiate without real Redis — just verify interface
        rl = RedisRateLimiter.__new__(RedisRateLimiter)
        assert hasattr(rl, "allow")


class TestVelocityDetection:
    """HSIP-1PHASE velocity anomaly pattern."""

    def test_high_velocity_warning(self):
        from three_surgeons.http.rate_limit import MemoryRateLimiter
        rl = MemoryRateLimiter(max_calls=200, window_s=60.0, warn_threshold=5)
        for _ in range(6):
            rl.allow("fast_agent")
        # After warn_threshold, velocity_warning flag set
        assert rl.velocity_warnings.get("fast_agent", 0) >= 1
