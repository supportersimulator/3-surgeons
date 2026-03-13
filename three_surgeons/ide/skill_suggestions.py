"""Live skill suggestion engine."""
from __future__ import annotations

import logging
import time
from typing import Any, Dict, List, Optional, Tuple

from three_surgeons.ide.event_bus import EventBus, EventEnvelope

logger = logging.getLogger(__name__)

SKILL_RULES: List[Tuple[str, str, float]] = [
    ("tests/", "test-driven-development", 0.85),
    ("test_", "test-driven-development", 0.80),
    (".test.", "test-driven-development", 0.80),
    ("spec/", "test-driven-development", 0.75),
    (".py", "systematic-debugging", 0.50),
    (".ts", "systematic-debugging", 0.50),
    (".tsx", "brainstorming", 0.40),
    (".css", "brainstorming", 0.35),
]


class SkillSuggestionEngine:
    def __init__(self, bus: EventBus, throttle_seconds: float = 10.0) -> None:
        self._bus = bus
        self._throttle_seconds = throttle_seconds
        self._last_suggestion_time: float = 0
        bus.on("ide.file_changed", self._on_file_changed)

    def _on_file_changed(self, event: EventEnvelope) -> None:
        now = time.monotonic()
        if now - self._last_suggestion_time < self._throttle_seconds:
            return
        path = event.payload.get("path", "")
        suggestion = self._analyze(path)
        if suggestion:
            self._last_suggestion_time = now
            self._bus.emit("skill.suggested", suggestion)

    def _analyze(self, path: str) -> Optional[Dict[str, Any]]:
        best_skill: Optional[str] = None
        best_confidence = 0.0
        for pattern, skill, confidence in SKILL_RULES:
            if pattern in path and confidence > best_confidence:
                best_skill = skill
                best_confidence = confidence
        if best_skill and best_confidence > 0.3:
            return {
                "skill": best_skill,
                "confidence": best_confidence,
                "reasoning": f"File pattern matched: {path}",
            }
        return None
