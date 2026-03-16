"""Chain segments, registry, executor, and state accumulator.

Composable chain segments are the atomic units of multi-step surgical
workflows. Each segment declares its requirements via CommandRequirements,
receives a RuntimeContext + shared state dict, and returns a CommandResult.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Optional, Set

from three_surgeons.core.requirements import (
    CommandRequirements,
    CommandResult,
    RuntimeContext,
)

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


# -- Stubs for Task 2 (ChainState, ChainExecutor) -------------------------
# These are placeholder classes so test imports don't fail.
# Full implementation comes in Task 2.


class ChainState:
    """Placeholder -- full implementation in Task 2."""

    pass


class ChainExecutor:
    """Placeholder -- full implementation in Task 2."""

    pass
