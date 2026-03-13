"""MCP subscription bridge -- manages stream lifecycle with TTL cleanup."""
from __future__ import annotations

import time
import uuid
from dataclasses import asdict
from typing import Any, Dict, List, Optional

from three_surgeons.ide.event_bus import EventBus, EventEnvelope


class MCPBridge:
    """Manages MCP event subscriptions with TTL-based cleanup.

    Each subscriber gets a stream_id backed by a per-stream queue.
    Stale streams (no poll within TTL) are cleaned up automatically.
    """

    def __init__(self, bus: EventBus, ttl_seconds: int = 300) -> None:
        self._bus = bus
        self._ttl_seconds = ttl_seconds
        self._streams: Dict[str, Dict[str, Any]] = {}

    def subscribe(self, patterns: List[str]) -> str:
        """Subscribe to event patterns, returns stream_id for polling."""
        stream_id = str(uuid.uuid4())
        queue: List[EventEnvelope] = []

        def handler(event: EventEnvelope) -> None:
            queue.append(event)

        self._streams[stream_id] = {
            "patterns": patterns,
            "handler": handler,
            "queue": queue,
            "last_poll": time.monotonic(),
        }
        for pattern in patterns:
            self._bus.on(pattern, handler)
        return stream_id

    def unsubscribe(self, stream_id: str) -> bool:
        """Remove a stream subscription. Returns False if stream_id unknown."""
        stream = self._streams.pop(stream_id, None)
        if stream is None:
            return False
        for pattern in stream["patterns"]:
            self._bus.off(pattern, stream["handler"])
        return True

    def publish(
        self,
        event_type: str,
        payload: Dict[str, Any],
        correlation_id: Optional[str] = None,
    ) -> str:
        """Publish an event via the bus, returns event id."""
        event = self._bus.emit(
            event_type, payload, source="mcp", correlation_id=correlation_id
        )
        return event.id

    def poll(self, stream_id: str) -> Optional[List[Dict[str, Any]]]:
        """Drain queued events for a stream. Returns None if stream unknown."""
        stream = self._streams.get(stream_id)
        if stream is None:
            return None
        stream["last_poll"] = time.monotonic()
        queue: List[EventEnvelope] = stream["queue"]
        events = [asdict(e) for e in queue]
        queue.clear()
        return events

    def cleanup_stale(self) -> int:
        """Remove streams that haven't polled within TTL. Returns count removed."""
        now = time.monotonic()
        stale = [
            sid
            for sid, s in self._streams.items()
            if now - s["last_poll"] > self._ttl_seconds
        ]
        for sid in stale:
            self.unsubscribe(sid)
        return len(stale)
