"""EventBus startup orchestrator — wires transports and bridges."""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Optional

from three_surgeons.ide.event_bus import EventBus

logger = logging.getLogger(__name__)


@dataclass
class EventBusConfig:
    """Configuration for EventBus startup."""

    buffer_size: int = 1000
    jsonl_path: Optional[str] = None
    enable_websocket: bool = True
    ws_host: str = "127.0.0.1"
    ws_port: int = 8031
    enable_sse: bool = False
    enable_skill_suggestions: bool = True
    suggestions_dir: Optional[str] = None


def create_event_bus(config: Optional[EventBusConfig] = None) -> EventBus:
    """Create and configure the EventBus singleton with transports."""
    if config is None:
        config = EventBusConfig()

    bus = EventBus.get_instance(buffer_size=config.buffer_size)

    # Already initialized (singleton)
    if bus._transports:
        return bus

    # JSONL transport
    if config.jsonl_path:
        from three_surgeons.ide.transports.jsonl import JSONLTransport
        bus.register_transport(JSONLTransport(config.jsonl_path))
        logger.info("Registered JSONL transport: %s", config.jsonl_path)

    # SSE transport
    if config.enable_sse:
        from three_surgeons.ide.transports.sse import SSETransport
        bus.register_transport(SSETransport())
        logger.info("Registered SSE transport")

    # Skill suggestions
    if config.enable_skill_suggestions:
        from three_surgeons.ide.skill_suggestions import SkillSuggestionEngine
        SkillSuggestionEngine(bus)
        logger.info("Skill suggestion engine attached")

    return bus
