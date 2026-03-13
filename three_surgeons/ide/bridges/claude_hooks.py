"""Claude Code hooks -> EventBus bridge."""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Dict, Optional

from three_surgeons.ide.event_bus import EventBus, EventEnvelope

logger = logging.getLogger(__name__)

HOOK_EVENT_MAP = {
    "PreToolUse": "ide.tool_use_started",
    "PostToolUse": "ide.tool_use_completed",
    "Notification": "ide.notification",
    "Stop": "ide.session_ended",
}


class ClaudeHooksBridge:
    """Maps Claude Code hook lifecycle events to EventBus events.

    Forward bridge: hook_name -> event_type via HOOK_EVENT_MAP.
    Reverse bridge: skill.suggested -> suggestions.json file.
    """

    def __init__(self, bus: EventBus, suggestions_dir: Optional[str] = None) -> None:
        self._bus = bus
        self._suggestions_dir = Path(suggestions_dir) if suggestions_dir else None
        if self._suggestions_dir:
            bus.on("skill.suggested", self._on_skill_suggested)

    def handle_hook(self, hook_name: str, data: Dict[str, Any]) -> None:
        """Translate a Claude Code hook into an EventBus event."""
        event_type = HOOK_EVENT_MAP.get(hook_name)
        if event_type is None:
            return
        self._bus.emit(event_type, data, source="hook")

    def _on_skill_suggested(self, event: EventEnvelope) -> None:
        """Reverse bridge: write skill suggestions to disk for Claude Code."""
        if self._suggestions_dir is None:
            return
        self._suggestions_dir.mkdir(parents=True, exist_ok=True)
        path = self._suggestions_dir / "suggestions.json"
        try:
            path.write_text(json.dumps(event.payload, indent=2))
        except OSError:
            logger.warning("Failed to write suggestions.json", exc_info=True)
