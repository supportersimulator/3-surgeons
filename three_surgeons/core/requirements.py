"""Command requirements schema and capability gate result types.

Each command declares its infrastructure requirements. The capability gate
checks these against detected runtime context and returns PROCEED/DEGRADED/BLOCKED.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List


class GateResult(Enum):
    """Outcome of checking a command's requirements against runtime capabilities."""
    PROCEED = "proceed"
    DEGRADED = "degraded"
    BLOCKED = "blocked"


@dataclass
class CommandRequirements:
    """What a command needs to run."""
    min_llms: int = 0
    needs_state: bool = False
    needs_evidence: bool = False
    needs_git: bool = False
    preconditions: List[str] = field(default_factory=list)
    recommended_llms: int = 0


@dataclass
class CommandResult:
    """Structured result from any command."""
    success: bool
    data: Dict[str, Any]
    degraded: bool = False
    degradation_notes: List[str] = field(default_factory=list)
    blocked: bool = False
    blocked_reason: str = ""

    def to_dict(self) -> Dict[str, Any]:
        """Serialize to a JSON-safe dict."""
        return {
            "success": self.success,
            "data": self.data,
            "degraded": self.degraded,
            "degradation_notes": self.degradation_notes,
            "blocked": self.blocked,
            "blocked_reason": self.blocked_reason,
        }

    @classmethod
    def blocked_result(cls, reason: str) -> "CommandResult":
        """Convenience constructor for blocked results."""
        return cls(success=False, data={}, blocked=True, blocked_reason=reason)
