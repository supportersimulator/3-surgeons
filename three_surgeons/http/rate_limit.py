"""Strategy-pattern rate limiter — in-memory default, Redis optional.

HSIP-1PHASE patterns:
- Sliding window with atomic operations
- Velocity anomaly detection (warn_threshold)
- Dormant Redis backend (activate when multi-machine)
"""
from __future__ import annotations

import logging
import time as _time
from collections import defaultdict
from typing import Protocol, runtime_checkable

logger = logging.getLogger(__name__)


@runtime_checkable
class RateLimiterLike(Protocol):
    def allow(self, key: str) -> bool: ...


class MemoryRateLimiter:
    """In-memory sliding window rate limiter with velocity detection."""

    def __init__(
        self,
        max_calls: int = 20,
        window_s: float = 60.0,
        warn_threshold: int = 100,
    ):
        self.max_calls = max_calls
        self.window_s = window_s
        self.warn_threshold = warn_threshold
        self._calls: dict[str, list[float]] = defaultdict(list)
        self.velocity_warnings: dict[str, int] = defaultdict(int)

    def allow(self, key: str) -> bool:
        now = _time.monotonic()
        calls = self._calls[key]
        self._calls[key] = [t for t in calls if now - t < self.window_s]
        # Velocity anomaly detection
        if len(self._calls[key]) >= self.warn_threshold:
            self.velocity_warnings[key] += 1
            logger.warning(
                "Velocity anomaly: %s at %d calls/%.0fs",
                key, len(self._calls[key]), self.window_s,
            )
        if len(self._calls[key]) >= self.max_calls:
            return False
        self._calls[key].append(now)
        return True


class RedisRateLimiter:
    """Redis-backed sliding window rate limiter (dormant — activate for multi-machine).

    Uses ZADD + ZRANGEBYSCORE for atomic sliding window.
    Drop-in replacement for MemoryRateLimiter.
    """

    def __init__(self, redis_client, max_calls: int = 20, window_s: float = 60.0):
        self._redis = redis_client
        self.max_calls = max_calls
        self.window_s = window_s

    def allow(self, key: str) -> bool:
        import time
        now = time.time()
        pipe = self._redis.pipeline()
        rkey = f"3s:ratelimit:{key}"
        pipe.zremrangebyscore(rkey, 0, now - self.window_s)
        pipe.zcard(rkey)
        pipe.zadd(rkey, {f"{now}": now})
        pipe.expire(rkey, int(self.window_s) + 1)
        results = pipe.execute()
        count = results[1]
        return count < self.max_calls


def create_rate_limiter(
    backend: str = "memory",
    redis_client=None,
    **kwargs,
) -> RateLimiterLike:
    """Factory for rate limiter backend selection."""
    if backend == "redis" and redis_client:
        return RedisRateLimiter(redis_client, **kwargs)
    return MemoryRateLimiter(**kwargs)
