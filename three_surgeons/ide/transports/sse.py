"""SSE fallback transport — queues events for HTTP polling."""
from __future__ import annotations

import json
import logging
from collections import deque
from dataclasses import asdict
from typing import List

from three_surgeons.ide.event_bus import EventEnvelope

logger = logging.getLogger(__name__)


class SSETransport:
    def __init__(self, max_queue: int = 200) -> None:
        self._queue: deque[EventEnvelope] = deque(maxlen=max_queue)

    def deliver(self, event: EventEnvelope) -> None:
        self._queue.append(event)

    def pending_events(self) -> List[EventEnvelope]:
        events = list(self._queue)
        self._queue.clear()
        return events

    def format_sse(self, event: EventEnvelope) -> str:
        data = json.dumps(asdict(event))
        return f"data: {data}\n\n"
