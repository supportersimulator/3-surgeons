"""Tests for SkillSuggestionEngine."""
from __future__ import annotations

import time
from unittest.mock import patch

import pytest

from three_surgeons.ide.event_bus import EventBus
from three_surgeons.ide.skill_suggestions import SkillSuggestionEngine


@pytest.fixture(autouse=True)
def _reset():
    yield
    EventBus.reset_instance()


class TestSkillSuggestionEngine:

    def test_file_change_triggers_suggestion(self):
        """A file change event should emit a skill.suggested event."""
        bus = EventBus()
        suggestions = []
        bus.on("skill.suggested", lambda e: suggestions.append(e))

        _engine = SkillSuggestionEngine(bus, throttle_seconds=0)
        bus.emit("ide.file_changed", {"path": "src/app.py"})

        assert len(suggestions) == 1
        assert suggestions[0].payload["skill"] == "systematic-debugging"

    def test_throttle_prevents_rapid_fire(self):
        """Throttle should prevent multiple suggestions within window."""
        bus = EventBus()
        suggestions = []
        bus.on("skill.suggested", lambda e: suggestions.append(e))

        _engine = SkillSuggestionEngine(bus, throttle_seconds=10)

        # Emit 3 file changes rapidly
        bus.emit("ide.file_changed", {"path": "src/app.py"})
        bus.emit("ide.file_changed", {"path": "src/utils.py"})
        bus.emit("ide.file_changed", {"path": "src/main.py"})

        # Only 1 suggestion should have been emitted
        assert len(suggestions) == 1

    def test_throttle_allows_after_window(self):
        """After throttle window expires, new suggestions are allowed."""
        bus = EventBus()
        suggestions = []
        bus.on("skill.suggested", lambda e: suggestions.append(e))

        engine = SkillSuggestionEngine(bus, throttle_seconds=0.05)

        bus.emit("ide.file_changed", {"path": "src/app.py"})
        assert len(suggestions) == 1

        # Wait for throttle to expire
        time.sleep(0.06)
        bus.emit("ide.file_changed", {"path": "src/utils.py"})
        assert len(suggestions) == 2

    def test_suggestion_includes_confidence(self):
        """Suggestion payload should include confidence between 0 and 1."""
        bus = EventBus()
        suggestions = []
        bus.on("skill.suggested", lambda e: suggestions.append(e))

        _engine = SkillSuggestionEngine(bus, throttle_seconds=0)
        bus.emit("ide.file_changed", {"path": "src/app.py"})

        assert len(suggestions) == 1
        confidence = suggestions[0].payload["confidence"]
        assert 0 < confidence <= 1

    def test_test_file_gets_tdd_suggestion(self):
        """Test file paths should get test-driven-development suggestion."""
        bus = EventBus()
        suggestions = []
        bus.on("skill.suggested", lambda e: suggestions.append(e))

        _engine = SkillSuggestionEngine(bus, throttle_seconds=0)
        bus.emit("ide.file_changed", {"path": "tests/test_feature.py"})

        assert len(suggestions) == 1
        assert suggestions[0].payload["skill"] == "test-driven-development"
        assert suggestions[0].payload["confidence"] >= 0.75

    def test_no_suggestion_for_unknown_file(self):
        """Files not matching any rule should not trigger suggestions."""
        bus = EventBus()
        suggestions = []
        bus.on("skill.suggested", lambda e: suggestions.append(e))

        _engine = SkillSuggestionEngine(bus, throttle_seconds=0)
        bus.emit("ide.file_changed", {"path": "README.md"})

        assert len(suggestions) == 0

    def test_suggestion_includes_reasoning(self):
        """Suggestion should include a reasoning string."""
        bus = EventBus()
        suggestions = []
        bus.on("skill.suggested", lambda e: suggestions.append(e))

        _engine = SkillSuggestionEngine(bus, throttle_seconds=0)
        bus.emit("ide.file_changed", {"path": "src/app.py"})

        assert "reasoning" in suggestions[0].payload
        assert "app.py" in suggestions[0].payload["reasoning"]
