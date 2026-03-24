"""Capabilities adapter system for 3-surgeons plugin.

Auto-detects available ecosystem infrastructure (Redis, Git, ContextDNA)
and builds a CompositeAdapter that enriches operations with telemetry,
evidence mirroring, git context, and observability.

Usage:
    from three_surgeons.adapters import AdapterContext, get_standalone

    # Auto-detect (recommended)
    with AdapterContext() as adapter:
        team = SurgeryTeam(cardio, neuro, evidence, state, adapter=adapter)
        team.cross_examine("topic")

    # Explicit standalone (no ecosystem)
    adapter = get_standalone()
"""
from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from ._protocol import Capability, GateBlockedError, SurgeryAdapter
from ._standalone import StandaloneAdapter
from ._composite import CompositeAdapter

logger = logging.getLogger(__name__)

__all__ = [
    "AdapterContext",
    "Capability",
    "CompositeAdapter",
    "GateBlockedError",
    "StandaloneAdapter",
    "SurgeryAdapter",
    "get_standalone",
]


def get_standalone() -> StandaloneAdapter:
    """Return a no-op adapter for users without ecosystem infra."""
    return StandaloneAdapter()


class AdapterContext:
    """Context manager for scoped adapter lifecycle.

    One per workflow, not singleton. Probes are cached for the context lifetime.
    """

    def __init__(self, config: Optional[Dict[str, Any]] = None) -> None:
        self._config = config
        self._adapter: Optional[SurgeryAdapter] = None

    def __enter__(self) -> SurgeryAdapter:
        try:
            from ._detection import auto_detect
            self._adapter = auto_detect(self._config)
        except ImportError:
            logger.debug("Detection module not available, using standalone")
            self._adapter = StandaloneAdapter()
        except Exception as exc:
            logger.warning("Auto-detection failed, using standalone: %s", exc)
            self._adapter = StandaloneAdapter()

        try:
            self._adapter.on_init()
        except Exception as exc:
            logger.warning("Adapter on_init failed: %s", exc)

        return self._adapter

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        if self._adapter:
            try:
                self._adapter.close()
            except Exception as exc:
                logger.warning("Adapter close failed: %s", exc)
            self._adapter = None
        return None  # Don't suppress exceptions
