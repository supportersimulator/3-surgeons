"""EventBus — singleton async-first event bus with ring buffer.

Core component of Phase 3 IDE event layer. Transport-agnostic pub/sub
with wildcard subscriptions, correlation tracking, and error isolation.
"""
from __future__ import annotations

import logging
import uuid
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional, Protocol

logger = logging.getLogger(__name__)


@dataclass
class EventEnvelope:
    """Immutable event envelope matching ContextDNA Event v1 schema."""

    id: str
    version: int
    type: str
    source: str
    timestamp: str
    payload: Dict[str, Any]
    metadata: Dict[str, Any] = field(default_factory=dict)


class Transport(Protocol):
    """Interface for event transports (WebSocket, SSE, JSONL)."""

    def deliver(self, event: EventEnvelope) -> None: ...


EventHandler = Callable[[EventEnvelope], None]


class EventBus:
    """Singleton-capable async-first event bus with ring buffer.

    Args:
        buffer_size: Max events in ring buffer (default 1000).
    """

    _instance: Optional[EventBus] = None

    def __init__(self, buffer_size: int = 1000) -> None:
        self._handlers: Dict[str, List[EventHandler]] = {}
        self._once_handlers: Dict[str, List[EventHandler]] = {}
        self._transports: List[Transport] = []
        self._buffer: deque[EventEnvelope] = deque(maxlen=buffer_size)
        self._buffer_size = buffer_size
        self._total_emitted = 0
        self.events_dropped = 0

    @classmethod
    def get_instance(cls, buffer_size: int = 1000) -> EventBus:
        if cls._instance is None:
            cls._instance = cls(buffer_size=buffer_size)
        return cls._instance

    @classmethod
    def reset_instance(cls) -> None:
        cls._instance = None

    def on(self, pattern: str, handler: EventHandler) -> None:
        self._handlers.setdefault(pattern, []).append(handler)

    def once(self, pattern: str, handler: EventHandler) -> None:
        self._once_handlers.setdefault(pattern, []).append(handler)

    def off(self, pattern: str, handler: EventHandler) -> None:
        if pattern in self._handlers:
            try:
                self._handlers[pattern].remove(handler)
            except ValueError:
                pass

    def emit(
        self,
        event_type: str,
        payload: Dict[str, Any],
        *,
        source: str = "python",
        correlation_id: Optional[str] = None,
        session_id: Optional[str] = None,
    ) -> EventEnvelope:
        metadata: Dict[str, Any] = {}
        if correlation_id:
            metadata["correlation_id"] = correlation_id
        if session_id:
            metadata["session_id"] = session_id

        event = EventEnvelope(
            id=str(uuid.uuid4()),
            version=1,
            type=event_type,
            source=source,
            timestamp=datetime.now(timezone.utc).isoformat(),
            payload=payload,
            metadata=metadata,
        )

        # Ring buffer
        if len(self._buffer) == self._buffer_size:
            self.events_dropped += 1
        self._buffer.append(event)
        self._total_emitted += 1

        # Notify handlers (exact + wildcard)
        self._notify(event)

        # Deliver to transports
        for transport in self._transports:
            try:
                transport.deliver(event)
            except Exception:
                logger.warning(
                    "Transport delivery failed for %s", event_type, exc_info=True
                )

        return event

    def _notify(self, event: EventEnvelope) -> None:
        for pattern, handlers in list(self._handlers.items()):
            if self._matches(pattern, event.type):
                for handler in list(handlers):
                    try:
                        handler(event)
                    except Exception:
                        logger.warning(
                            "Handler error for %s", event.type, exc_info=True
                        )

        # Once handlers
        for pattern, handlers in list(self._once_handlers.items()):
            if self._matches(pattern, event.type):
                for handler in list(handlers):
                    try:
                        handler(event)
                    except Exception:
                        logger.warning(
                            "Once handler error for %s", event.type, exc_info=True
                        )
                del self._once_handlers[pattern]

    @staticmethod
    def _matches(pattern: str, event_type: str) -> bool:
        if pattern == "*":
            return True
        if pattern.endswith(".*"):
            prefix = pattern[:-2]
            return event_type.startswith(prefix + ".")
        return pattern == event_type

    def recent_events(self, n: int = 10) -> List[EventEnvelope]:
        items = list(self._buffer)
        return items[-n:] if n < len(items) else items

    def register_transport(self, transport: Transport) -> None:
        self._transports.append(transport)

    def remove_transport(self, transport: Transport) -> None:
        try:
            self._transports.remove(transport)
        except ValueError:
            pass
