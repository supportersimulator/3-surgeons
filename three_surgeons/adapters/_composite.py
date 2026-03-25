"""CompositeAdapter — fan-out to N adapters with per-adapter error isolation."""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from ._protocol import Capability, GateBlockedError, SurgeryAdapter

logger = logging.getLogger(__name__)


class CompositeAdapter:
    """Fan-out adapter that delegates to multiple adapters in order.

    Per-adapter try/except ensures one failing adapter never breaks others.
    Zero Silent Failures: every exception is logged via on_error + logger.

    Ordering: Git adapter should be first (enriches topic for downstream).
    Telemetry adapters (Redis, Observability) are order-independent.
    """

    def __init__(self, adapters: List[SurgeryAdapter],
                 fail_fast: bool = False,
                 gate_mode: str = "block") -> None:
        self._adapters = list(adapters)
        self._fail_fast = fail_fast
        self._gate_mode = gate_mode
        self._error_counts: Dict[str, int] = {}

    @property
    def capabilities(self) -> Capability:
        result = Capability.NONE
        for adapter in self._adapters:
            try:
                result |= adapter.capabilities
            except Exception as exc:  # pragma: no cover
                adapter_id = type(adapter).__name__
                logger.warning("Adapter %s.capabilities probe failed: %s",
                               adapter_id, exc)
                self._error_counts[adapter_id] = self._error_counts.get(adapter_id, 0) + 1
        return result

    @property
    def thread_safe(self) -> bool:
        return all(
            getattr(a, 'thread_safe', True) for a in self._adapters
        )

    def _safe_call(self, method: str, *args: Any, **kwargs: Any) -> None:
        """Call method on each adapter with error isolation."""
        for adapter in self._adapters:
            try:
                getattr(adapter, method)(*args, **kwargs)
            except Exception as exc:
                adapter_name = type(adapter).__name__
                logger.error("Adapter %s.%s failed: %s", adapter_name, method, exc)
                self._error_counts[adapter_name] = self._error_counts.get(adapter_name, 0) + 1
                try:
                    adapter.on_error(method, exc, {"args": args, "kwargs": kwargs})
                except Exception:
                    pass  # on_error itself failed — already logged above
                if self._fail_fast:
                    raise

    def on_init(self) -> None:
        self._safe_call("on_init")

    def on_workflow_start(self, operation: str, topic: str) -> None:
        self._safe_call("on_workflow_start", operation, topic)

    def on_workflow_end(self, operation: str, topic: str, result: Any,
                        error: Optional[Exception] = None) -> None:
        self._safe_call("on_workflow_end", operation, topic, result, error)

    def on_cost(self, surgeon: str, cost_usd: float, operation: str) -> None:
        self._safe_call("on_cost", surgeon, cost_usd, operation)

    def on_cross_exam_logged(self, topic: str, data: Dict[str, Any]) -> None:
        self._safe_call("on_cross_exam_logged", topic, data)

    def on_error(self, operation: str, error: Exception,
                 context: Dict[str, Any]) -> None:
        self._safe_call("on_error", operation, error, context)

    def enrich_topic(self, topic: str, operation: str) -> str:
        """Sequential chaining — each adapter enriches, returns new string."""
        for adapter in self._adapters:
            try:
                topic = adapter.enrich_topic(topic, operation)
            except Exception as exc:
                adapter_name = type(adapter).__name__
                logger.error("Adapter %s.enrich_topic failed: %s",
                           adapter_name, exc)
                # Continue with unenriched topic — don't break chain
        return topic

    def check_gate(self, operation: str) -> Optional[str]:
        """Run all gates. First blocker wins (if gate_mode=block)."""
        for adapter in self._adapters:
            try:
                reason = adapter.check_gate(operation)
                if reason:
                    if self._gate_mode == "block":
                        raise GateBlockedError(
                            f"{type(adapter).__name__}: {reason}"
                        )
                    else:
                        logger.warning("Gate advisory from %s: %s",
                                     type(adapter).__name__, reason)
                        return reason
            except GateBlockedError:
                raise
            except Exception as exc:
                logger.error("Adapter %s.check_gate failed: %s",
                           type(adapter).__name__, exc)
        return None

    def on_user_action(self, action: str, metadata: Dict[str, Any]) -> None:
        self._safe_call("on_user_action", action, metadata)

    def close(self) -> None:
        """Close all adapters. Errors logged but never propagated."""
        for adapter in self._adapters:
            try:
                adapter.close()
            except Exception as exc:
                logger.error("Adapter %s.close failed: %s",
                           type(adapter).__name__, exc)
