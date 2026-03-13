"""IDE event bus layer — Phase 3 of ContextDNA integration."""
from three_surgeons.ide.event_bus import EventBus, EventEnvelope
from three_surgeons.ide.event_types import EventNamespace, validate_event_type

try:
    from three_surgeons.ide.startup import create_event_bus
except ImportError:
    create_event_bus = None  # type: ignore[assignment]

__all__ = [
    "EventBus",
    "EventEnvelope",
    "EventNamespace",
    "validate_event_type",
    "create_event_bus",
]
