"""Event schema types and namespace registry for ContextDNA Event v1."""
from __future__ import annotations

from enum import Enum
from typing import Any, Dict, Tuple


class InvalidEventTypeError(ValueError):
    """Raised when an event type fails validation."""


class EventNamespace(Enum):
    """Dotted namespace prefixes for events."""

    INJECTION = "injection"
    EVIDENCE = "evidence"
    SKILL = "skill"
    HEALTH = "health"
    IDE = "ide"
    SURGEON = "surgeon"
    PHASE = "phase"
    BREAKER = "breaker"


NAMESPACE_REGISTRY: Dict[EventNamespace, Dict[str, Any]] = {
    EventNamespace.INJECTION: {
        "examples": ["injection.completed", "injection.failed"],
        "direction": "python_to_ts",
    },
    EventNamespace.EVIDENCE: {
        "examples": ["evidence.collected", "evidence.graded"],
        "direction": "python_to_ts",
    },
    EventNamespace.SKILL: {
        "examples": ["skill.suggested", "skill.activated", "skill.completed"],
        "direction": "bidirectional",
    },
    EventNamespace.HEALTH: {
        "examples": ["health.check", "health.degraded", "health.recovered"],
        "direction": "python_to_ts",
    },
    EventNamespace.IDE: {
        "examples": ["ide.file_changed", "ide.selection_changed"],
        "direction": "ts_to_python",
    },
    EventNamespace.SURGEON: {
        "examples": ["surgeon.cross_exam_started", "surgeon.consensus_reached"],
        "direction": "python_to_ts",
    },
    EventNamespace.PHASE: {
        "examples": ["phase.detected", "phase.transition"],
        "direction": "python_to_ts",
    },
    EventNamespace.BREAKER: {
        "examples": ["breaker.tripped", "breaker.reset"],
        "direction": "reserved",
    },
}


def validate_event_type(event_type: str) -> bool:
    """Validate event type against namespace registry.

    Raises InvalidEventTypeError if invalid. Returns True if valid.
    """
    if "." not in event_type:
        raise InvalidEventTypeError(
            f"Event type must be dotted (got {event_type!r})"
        )

    namespace_str = event_type.split(".")[0]

    try:
        EventNamespace(namespace_str)
    except ValueError:
        raise InvalidEventTypeError(
            f"Unknown namespace {namespace_str!r} in {event_type!r}. "
            f"Valid: {[ns.value for ns in EventNamespace]}"
        )

    return True


def parse_event_type(event_type: str) -> Tuple[EventNamespace, str]:
    """Parse event type into (namespace, action)."""
    validate_event_type(event_type)
    parts = event_type.split(".", 1)
    return EventNamespace(parts[0]), parts[1]
