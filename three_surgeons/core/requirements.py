"""Command requirements schema and capability gate result types.

Each command declares its infrastructure requirements. The capability gate
checks these against detected runtime context and returns PROCEED/DEGRADED/BLOCKED.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Tuple


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


@dataclass
class RuntimeContext:
    """Detected runtime capabilities, built once per invocation."""
    healthy_llms: List[Any]
    state: Any  # StateBackend or None
    evidence: Any  # EvidenceStore or None
    git_available: bool
    git_root: Optional[str]
    config: Any  # Config
    precondition_checker: Optional[Callable[[str], Tuple[bool, str]]] = None


def check_requirements(
    reqs: CommandRequirements,
    ctx: RuntimeContext,
) -> Tuple[GateResult, List[str]]:
    """Check command requirements against runtime context.

    Returns (gate_result, notes). Notes explain blocks or degradations.
    BLOCKED conditions are checked first — if any block, return immediately.
    DEGRADED conditions are collected and returned if no blocks exist.
    """
    blocks: List[str] = []
    degrades: List[str] = []

    # Hard requirements — any failure blocks
    if reqs.min_llms > 0 and len(ctx.healthy_llms) < reqs.min_llms:
        blocks.append(
            f"Requires at least {reqs.min_llms} LLM endpoint(s), "
            f"found {len(ctx.healthy_llms)}. Run `3s setup-check` to diagnose."
        )

    if reqs.needs_state and ctx.state is None:
        blocks.append("Requires a state backend. Run `3s setup-check` to diagnose.")

    if reqs.needs_evidence and ctx.evidence is None:
        blocks.append("Requires an evidence store. Run `3s setup-check` to diagnose.")

    if reqs.needs_git and not ctx.git_available:
        blocks.append("Requires a git repository for codebase analysis.")

    # Preconditions
    for pre in reqs.preconditions:
        if ctx.precondition_checker:
            ok, reason = ctx.precondition_checker(pre)
            if not ok:
                blocks.append(reason or f"Precondition failed: {pre}")
        else:
            blocks.append(f"Cannot check precondition '{pre}': no checker configured.")

    if blocks:
        return GateResult.BLOCKED, blocks

    # Soft requirements — degraded but not blocked
    if reqs.recommended_llms > 0 and len(ctx.healthy_llms) < reqs.recommended_llms:
        degrades.append(
            f"Running with {len(ctx.healthy_llms)} surgeon(s) "
            f"({reqs.recommended_llms} recommended for full cross-examination)."
        )

    if degrades:
        return GateResult.DEGRADED, degrades

    return GateResult.PROCEED, []
