"""StandaloneAdapter — no-op default for users without ecosystem infra."""
from __future__ import annotations

from typing import Any, Dict, Optional

from ._protocol import Capability, SurgeryAdapter


class StandaloneAdapter:
    """No-op adapter. All hooks do nothing. Zero overhead."""

    @property
    def capabilities(self) -> Capability:
        return Capability.NONE

    @property
    def thread_safe(self) -> bool:
        return True

    def on_init(self) -> None:
        pass

    def on_workflow_start(self, operation: str, topic: str) -> None:
        pass

    def on_workflow_end(self, operation: str, topic: str, result: Any,
                        error: Optional[Exception] = None) -> None:
        pass

    def on_cost(self, surgeon: str, cost_usd: float, operation: str) -> None:
        pass

    def on_cross_exam_logged(self, topic: str, data: Dict[str, Any]) -> None:
        pass

    def on_error(self, operation: str, error: Exception,
                 context: Dict[str, Any]) -> None:
        pass

    def enrich_topic(self, topic: str, operation: str) -> str:
        return topic

    def check_gate(self, operation: str) -> Optional[str]:
        return None

    def on_user_action(self, action: str, metadata: Dict[str, Any]) -> None:
        pass

    def close(self) -> None:
        pass
