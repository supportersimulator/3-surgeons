"""Chain segments, registry, executor, and state accumulator.

Composable chain segments are the atomic units of multi-step surgical
workflows. Each segment declares its requirements via CommandRequirements,
receives a RuntimeContext + shared state dict, and returns a CommandResult.
"""
from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Set, Tuple

from three_surgeons.core.requirements import (
    CommandRequirements,
    CommandResult,
    GateResult,
    RuntimeContext,
    check_requirements,
)
from three_surgeons.core.state import StateBackend

logger = logging.getLogger(__name__)

# -- ChainSegment & Registry ----------------------------------------------


@dataclass
class ChainSegment:
    """Atomic unit of a chain -- a decorated function with requirements."""

    name: str
    fn: Callable[[RuntimeContext, dict], CommandResult]
    requires: CommandRequirements
    tags: Set[str] = field(default_factory=set)
    learned_deps: Set[str] = field(default_factory=set)
    learned_synergies: Set[str] = field(default_factory=set)


SEGMENT_REGISTRY: Dict[str, ChainSegment] = {}


def segment(
    name: str,
    requires: CommandRequirements,
    tags: Optional[Set[str]] = None,
) -> Callable:
    """Decorator that registers a function as a chain segment."""

    def decorator(fn: Callable) -> Callable:
        if name in SEGMENT_REGISTRY:
            raise ValueError(
                f"Segment '{name}' already registered. "
                f"Existing: {SEGMENT_REGISTRY[name].fn.__name__}, "
                f"new: {fn.__name__}"
            )
        seg = ChainSegment(
            name=name,
            fn=fn,
            requires=requires,
            tags=tags or set(),
        )
        SEGMENT_REGISTRY[name] = seg
        return fn

    return decorator


# ── ChainState ────────────────────────────────────────────────────────


@dataclass
class ChainState:
    """Accumulator passed through a chain execution."""

    data: Dict[str, Any] = field(default_factory=dict)
    skipped: List[Tuple[str, List[str]]] = field(default_factory=list)
    degraded: List[Tuple[str, List[str]]] = field(default_factory=list)
    segment_results: Dict[str, CommandResult] = field(default_factory=dict)
    segment_times_ns: Dict[str, int] = field(default_factory=dict)
    errors: List[Tuple[str, str]] = field(default_factory=list)
    total_ns: int = 0
    halted: bool = False
    halt_reason: str = ""


# ── ChainExecutor ────────────────────────────────────────────────────


class ChainExecutor:
    """Runs an ordered list of segments with capability gating."""

    def __init__(
        self,
        state_backend: StateBackend,
        halt_on_error: bool = False,
    ) -> None:
        self._state = state_backend
        self._halt_on_error = halt_on_error

    def run(
        self,
        segment_names: List[str],
        ctx: RuntimeContext,
        initial_data: Optional[Dict[str, Any]] = None,
    ) -> ChainState:
        """Execute segments in order, accumulating results."""
        chain_state = ChainState(data=initial_data or {})

        for name in segment_names:
            if chain_state.halted:
                break

            seg = SEGMENT_REGISTRY[name]  # KeyError if unknown — intentional
            gate, notes = check_requirements(seg.requires, ctx)

            if gate == GateResult.BLOCKED:
                chain_state.skipped.append((name, notes))
                continue

            if gate == GateResult.DEGRADED:
                chain_state.degraded.append((name, notes))

            t0 = time.time_ns()
            try:
                result = seg.fn(ctx, chain_state.data)
                chain_state.segment_results[name] = result
                if result.success and result.data:
                    chain_state.data.update(result.data)
            except Exception as exc:
                chain_state.errors.append((name, str(exc)))
                if self._halt_on_error:
                    chain_state.halted = True
                    chain_state.halt_reason = str(exc)
            chain_state.segment_times_ns[name] = time.time_ns() - t0

        chain_state.total_ns = sum(chain_state.segment_times_ns.values())
        self._record_execution(segment_names, chain_state)
        return chain_state

    def _record_execution(
        self,
        segment_names: List[str],
        chain_state: ChainState,
    ) -> None:
        """Write execution record to state backend for telemetry."""
        ran = list(chain_state.segment_results.keys())
        record = {
            "segments_requested": segment_names,
            "segments_run": ran,
            "segments_skipped": [s[0] for s in chain_state.skipped],
            "success": len(chain_state.errors) == 0,
            "duration_ms": chain_state.total_ns / 1_000_000,
            "timestamp": time.time(),
        }
        self._state.list_push(
            "chain:executions",
            json.dumps(record),
        )
