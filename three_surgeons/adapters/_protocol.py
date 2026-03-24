"""SurgeryAdapter protocol — defines the hook interface for ecosystem adapters."""
from __future__ import annotations

from enum import Flag, auto
from typing import Any, Dict, Optional, Protocol, runtime_checkable


class Capability(Flag):
    """Bit flags for adapter capabilities. Adapters declare what they provide."""
    NONE = 0
    COST_TELEMETRY = auto()
    EVIDENCE_MIRROR = auto()
    GIT_CONTEXT = auto()
    GAINS_GATE = auto()
    OBSERVABILITY = auto()
    CRITICAL_FINDINGS = auto()


class GateBlockedError(RuntimeError):
    """Raised when check_gate blocks a workflow."""
    pass


@runtime_checkable
class SurgeryAdapter(Protocol):
    """Protocol for ecosystem adapters that enrich 3-surgeons operations.

    Adapters hook into SurgeryTeam lifecycle to provide telemetry, enrichment,
    gating, and observability. Default implementations are no-ops.
    """

    @property
    def capabilities(self) -> Capability: ...

    @property
    def thread_safe(self) -> bool: ...

    # Lifecycle (3)
    def on_init(self) -> None: ...
    def on_workflow_start(self, operation: str, topic: str) -> None: ...
    def on_workflow_end(self, operation: str, topic: str, result: Any,
                        error: Optional[Exception] = None) -> None: ...

    # Data hooks (3)
    def on_cost(self, surgeon: str, cost_usd: float, operation: str) -> None: ...
    def on_cross_exam_logged(self, topic: str, data: Dict[str, Any]) -> None: ...
    def on_error(self, operation: str, error: Exception,
                 context: Dict[str, Any]) -> None: ...

    # Enrichment (1) — returns new topic string (immutable pattern)
    def enrich_topic(self, topic: str, operation: str) -> str: ...

    # Gating (1) — returns None (pass) or reason string (block/warn)
    def check_gate(self, operation: str) -> Optional[str]: ...

    # User interaction (1)
    def on_user_action(self, action: str, metadata: Dict[str, Any]) -> None: ...

    # Cleanup (1)
    def close(self) -> None: ...
