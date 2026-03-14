"""Cross-boundary probe protocol for capability registry.

3-surgeons defines this protocol. context-dna (or any external system)
provides concrete implementations. The registry accepts any object
satisfying this protocol — no cross-submodule imports needed.
"""
from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class CapabilityProbe(Protocol):
    """Protocol for infrastructure health probes.

    Implementations live outside 3-surgeons (e.g., in context-dna).
    The registry consumes them via duck typing.
    """

    def name(self) -> str:
        """Unique probe identifier (e.g., 'redis_health')."""
        ...

    def probe(self) -> bool:
        """Run the health check. Returns True if healthy."""
        ...

    def capability(self) -> str:
        """Which capability this probe checks (e.g., 'state_backend')."""
        ...
