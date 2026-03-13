"""Tests for Claude Code hooks -> EventBus bridge."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from three_surgeons.ide.event_bus import EventBus, EventEnvelope
from three_surgeons.ide.bridges.claude_hooks import ClaudeHooksBridge, HOOK_EVENT_MAP


@pytest.fixture(autouse=True)
def _reset_bus():
    yield
    EventBus.reset_instance()


@pytest.fixture
def bus() -> EventBus:
    return EventBus()


class TestHookMapping:
    """Forward bridge: hook_name -> event_type."""

    @pytest.mark.parametrize(
        "hook_name,expected_event",
        [
            ("PreToolUse", "ide.tool_use_started"),
            ("PostToolUse", "ide.tool_use_completed"),
            ("Notification", "ide.notification"),
            ("Stop", "ide.session_ended"),
        ],
    )
    def test_hook_maps_to_event(self, bus: EventBus, hook_name: str, expected_event: str) -> None:
        bridge = ClaudeHooksBridge(bus)
        received: list[EventEnvelope] = []
        bus.on(expected_event, received.append)

        bridge.handle_hook(hook_name, {"tool": "Read", "path": "/tmp/x"})

        assert len(received) == 1
        assert received[0].type == expected_event
        assert received[0].payload == {"tool": "Read", "path": "/tmp/x"}

    def test_source_is_hook(self, bus: EventBus) -> None:
        bridge = ClaudeHooksBridge(bus)
        received: list[EventEnvelope] = []
        bus.on("ide.tool_use_started", received.append)

        bridge.handle_hook("PreToolUse", {"tool": "Bash"})

        assert received[0].source == "hook"

    def test_unknown_hook_ignored(self, bus: EventBus) -> None:
        bridge = ClaudeHooksBridge(bus)
        received: list[EventEnvelope] = []
        bus.on("*", received.append)

        bridge.handle_hook("UnknownHook", {"data": 1})

        assert len(received) == 0


class TestReverseBridge:
    """Reverse bridge: skill.suggested -> suggestions.json."""

    def test_skill_suggested_writes_file(self, bus: EventBus, tmp_path: Path) -> None:
        suggestions_dir = tmp_path / "suggestions"
        bridge = ClaudeHooksBridge(bus, suggestions_dir=str(suggestions_dir))

        payload = {"skills": ["commit", "review-pr"], "confidence": 0.9}
        bus.emit("skill.suggested", payload, source="engine")

        outfile = suggestions_dir / "suggestions.json"
        assert outfile.exists()
        written = json.loads(outfile.read_text())
        assert written == payload

    def test_no_suggestions_dir_no_crash(self, bus: EventBus) -> None:
        bridge = ClaudeHooksBridge(bus)  # no suggestions_dir
        # Should not raise
        bus.emit("skill.suggested", {"skills": []}, source="engine")

    def test_suggestions_dir_created_on_demand(self, bus: EventBus, tmp_path: Path) -> None:
        nested = tmp_path / "deep" / "nested" / "dir"
        bridge = ClaudeHooksBridge(bus, suggestions_dir=str(nested))

        bus.emit("skill.suggested", {"x": 1}, source="engine")

        assert (nested / "suggestions.json").exists()
