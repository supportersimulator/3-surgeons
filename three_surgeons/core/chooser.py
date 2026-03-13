# three_surgeons/core/chooser.py
"""Integration depth chooser for Phase 2 shared state layer.

Determines optimal integration depth based on detected capabilities.
Proactive environment audit → data-driven recommendation.
"""
from __future__ import annotations

import enum
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


class IntegrationDepth(enum.Enum):
    """Available integration depths. Each is additive, independently revertable."""

    MINIMAL = "minimal"      # Redis-backed state only
    STANDARD = "standard"    # State + evidence migration
    FULL = "full"            # State + evidence + LLM routing via shared lock
    CUSTOM = "custom"        # Per-capability selection


@dataclass
class IntegrationPlan:
    """Concrete plan for integration at a given depth."""

    depth: IntegrationDepth
    description: str
    config_changes: List[Dict[str, Any]] = field(default_factory=list)
    available_depths: List[IntegrationDepth] = field(default_factory=list)


def choose_integration_depth(
    capabilities: Dict[str, Any],
    redis_available: bool = False,
    contextdna_available: bool = False,
    user_preference: Optional[str] = None,
) -> Optional[IntegrationPlan]:
    """Choose integration depth based on detected capabilities.

    Args:
        capabilities: Response from GET /capabilities (or empty dict).
        redis_available: Whether Redis responded to PING.
        contextdna_available: Whether ContextDNA /health responded.
        user_preference: User's explicit choice ("minimal"/"standard"/"full"/"custom").

    Returns:
        IntegrationPlan or None if no upgrade is possible.
    """
    if not redis_available and not contextdna_available:
        return None

    features = capabilities.get("features", [])
    endpoints = capabilities.get("endpoints", {})

    # Determine available depths
    available: List[IntegrationDepth] = []

    if redis_available:
        available.append(IntegrationDepth.MINIMAL)

    if redis_available and "evidence_store" in features:
        available.append(IntegrationDepth.STANDARD)

    if redis_available and "evidence_store" in features and "priority_queue" in features:
        available.append(IntegrationDepth.FULL)

    if not available:
        available.append(IntegrationDepth.MINIMAL)

    # User preference overrides auto-detection
    if user_preference:
        try:
            depth = IntegrationDepth(user_preference)
        except ValueError:
            depth = available[-1]
    else:
        depth = available[-1]

    # Build config changes and description
    config_changes: List[Dict[str, Any]] = []
    description = ""

    if depth == IntegrationDepth.MINIMAL:
        description = "Redis-backed state only. Evidence and LLM stay local."
        config_changes.append({
            "section": "state",
            "key": "backend",
            "value": "redis",
        })

    elif depth == IntegrationDepth.STANDARD:
        description = "Redis state + evidence migration to shared store."
        config_changes.append({"section": "state", "key": "backend", "value": "redis"})
        if "evidence" in endpoints:
            config_changes.append({
                "section": "contextdna",
                "key": "evidence_endpoint",
                "value": endpoints["evidence"],
            })

    elif depth == IntegrationDepth.FULL:
        description = (
            "Full integration: state + evidence + LLM routing "
            "through shared priority lock."
        )
        config_changes.append({"section": "state", "key": "backend", "value": "redis"})
        if "evidence" in endpoints:
            config_changes.append({
                "section": "contextdna",
                "key": "evidence_endpoint",
                "value": endpoints["evidence"],
            })
        config_changes.append({"section": "queue", "key": "backend", "value": "redis"})
        if "priority_queue" in endpoints:
            config_changes.append({
                "section": "queue",
                "key": "endpoint",
                "value": endpoints["priority_queue"],
            })

    return IntegrationPlan(
        depth=depth,
        description=description,
        config_changes=config_changes,
        available_depths=available,
    )
