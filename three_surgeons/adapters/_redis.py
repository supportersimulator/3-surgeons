"""RedisAdapter — mirrors cost telemetry and evidence to Redis."""
from __future__ import annotations

import json
import logging
import time
from typing import Any, Dict, Optional

from ._protocol import Capability, SurgeryAdapter

logger = logging.getLogger(__name__)


class RedisAdapter:
    """Mirrors 3-surgeons telemetry to Redis for dashboard/webhook consumption.

    Writes to:
    - surgeons:costs:{date} — daily cost hash
    - surgeons:cross_exam_results — recent cross-exam list (capped at 50)
    - surgeons:errors — error counter hash
    - surgeons:workflow_active — current workflow marker (TTL 5min)
    """

    def __init__(self, host: str = "127.0.0.1", port: int = 6379,
                 socket_timeout: float = 1.0) -> None:
        try:
            import redis as redis_lib
            self._redis = redis_lib.Redis(
                host=host, port=port,
                decode_responses=True,
                socket_timeout=socket_timeout,
            )
        except ImportError:
            raise ImportError("redis package required for RedisAdapter")

    @property
    def capabilities(self) -> Capability:
        return Capability.COST_TELEMETRY | Capability.EVIDENCE_MIRROR

    @property
    def thread_safe(self) -> bool:
        return True

    def on_init(self) -> None:
        pass

    def on_workflow_start(self, operation: str, topic: str) -> None:
        try:
            self._redis.setex(
                "surgeons:workflow_active",
                300,  # 5min TTL
                json.dumps({"operation": operation, "topic": topic[:200],
                           "started": time.time()}),
            )
        except Exception as exc:
            logger.debug("Redis workflow_start failed: %s", exc)

    def on_workflow_end(self, operation: str, topic: str, result: Any,
                        error: Optional[Exception] = None) -> None:
        try:
            self._redis.delete("surgeons:workflow_active")
        except Exception as exc:
            logger.debug("Redis workflow_end failed: %s", exc)

    def on_cost(self, surgeon: str, cost_usd: float, operation: str) -> None:
        try:
            date_key = time.strftime("%Y-%m-%d")
            pipe = self._redis.pipeline(transaction=False)
            pipe.hincrbyfloat(f"surgeons:costs:{date_key}", surgeon, cost_usd)
            pipe.hincrbyfloat(f"surgeons:costs:{date_key}", "total", cost_usd)
            pipe.expire(f"surgeons:costs:{date_key}", 604800)  # 7d TTL
            pipe.execute()
        except Exception as exc:
            logger.debug("Redis on_cost failed: %s", exc)

    def on_cross_exam_logged(self, topic: str, data: Dict[str, Any]) -> None:
        try:
            entry = json.dumps({
                "topic": topic[:200],
                "timestamp": time.time(),
                **{k: v for k, v in data.items()
                   if isinstance(v, (str, int, float, bool, type(None)))},
            })
            pipe = self._redis.pipeline(transaction=False)
            pipe.lpush("surgeons:cross_exam_results", entry)
            pipe.ltrim("surgeons:cross_exam_results", 0, 49)  # Keep last 50
            pipe.expire("surgeons:cross_exam_results", 86400)  # 24h TTL
            pipe.execute()
        except Exception as exc:
            logger.debug("Redis on_cross_exam_logged failed: %s", exc)

    def on_error(self, operation: str, error: Exception,
                 context: Dict[str, Any]) -> None:
        try:
            self._redis.hincrby("surgeons:errors", operation, 1)
            self._redis.expire("surgeons:errors", 86400)
        except Exception:
            pass  # Don't recurse on error logging

    def enrich_topic(self, topic: str, operation: str) -> str:
        return topic  # Redis doesn't enrich topics

    def check_gate(self, operation: str) -> Optional[str]:
        return None  # Redis doesn't gate operations

    def on_user_action(self, action: str, metadata: Dict[str, Any]) -> None:
        pass

    def close(self) -> None:
        try:
            self._redis.close()
        except Exception:
            pass
