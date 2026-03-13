"""MCP event subscription tools for EventBus integration."""
from __future__ import annotations

import uuid
from dataclasses import asdict
from typing import Any, Dict, List

from three_surgeons.ide.event_bus import EventBus, EventEnvelope

_streams: Dict[str, Dict[str, Any]] = {}


def event_subscribe(bus: EventBus, patterns: List[str]) -> Dict[str, Any]:
    stream_id = str(uuid.uuid4())
    queue: List[EventEnvelope] = []

    def handler(event: EventEnvelope) -> None:
        queue.append(event)

    _streams[stream_id] = {"patterns": patterns, "handler": handler, "queue": queue}
    for pattern in patterns:
        bus.on(pattern, handler)
    return {"stream_id": stream_id, "patterns": patterns}


def event_unsubscribe(bus: EventBus, stream_id: str) -> Dict[str, Any]:
    stream = _streams.pop(stream_id, None)
    if stream is None:
        return {"removed": False, "reason": "unknown stream_id"}
    for pattern in stream["patterns"]:
        bus.off(pattern, stream["handler"])
    return {"removed": True}


def event_publish(
    bus: EventBus,
    event_type: str,
    payload: Dict[str, Any] | None = None,
    correlation_id: str | None = None,
) -> Dict[str, Any]:
    event = bus.emit(
        event_type, payload or {}, source="mcp", correlation_id=correlation_id
    )
    return {"emitted": True, "event_id": event.id}


def event_poll(bus: EventBus, stream_id: str) -> Dict[str, Any]:
    stream = _streams.get(stream_id)
    if stream is None:
        return {"events": [], "error": "unknown stream_id"}
    queue: List[EventEnvelope] = stream["queue"]
    events = [asdict(e) for e in queue]
    queue.clear()
    return {"events": events}


def _reset_streams() -> None:
    """Test helper -- clear all stream state."""
    _streams.clear()
