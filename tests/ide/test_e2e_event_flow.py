"""E2E tests: full event flow from emit -> transport -> handler."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from three_surgeons.ide.event_bus import EventBus
from three_surgeons.ide.event_types import validate_event_type
from three_surgeons.ide.transports.jsonl import JSONLTransport
from three_surgeons.ide.transports.sse import SSETransport
from three_surgeons.ide.bridges.claude_hooks import ClaudeHooksBridge
from three_surgeons.ide.bridges.mcp_tools import MCPBridge
from three_surgeons.ide.skill_suggestions import SkillSuggestionEngine


@pytest.fixture(autouse=True)
def reset():
    yield
    EventBus.reset_instance()


class TestE2EEventFlow:

    def test_emit_reaches_jsonl_and_handler(self, tmp_path):
        jsonl_path = str(tmp_path / ".events.jsonl")
        bus = EventBus()
        bus.register_transport(JSONLTransport(jsonl_path))

        received = []
        bus.on("injection.*", lambda e: received.append(e))
        bus.emit("injection.completed", {"doc": "test.py"})

        assert len(received) == 1
        lines = Path(jsonl_path).read_text().strip().split("\n")
        assert len(lines) == 1
        data = json.loads(lines[0])
        assert data["type"] == "injection.completed"

    def test_hook_bridge_to_mcp_poll(self):
        bus = EventBus()
        bridge = ClaudeHooksBridge(bus)
        mcp = MCPBridge(bus)
        stream_id = mcp.subscribe(["ide.*"])

        bridge.handle_hook("PreToolUse", {"tool_name": "Read"})

        events = mcp.poll(stream_id)
        assert events is not None
        assert len(events) == 1
        assert events[0]["type"] == "ide.tool_use_started"

    def test_skill_suggestion_chain(self):
        bus = EventBus()
        engine = SkillSuggestionEngine(bus, throttle_seconds=0)
        suggestions = []
        bus.on("skill.suggested", lambda e: suggestions.append(e))

        bus.emit("ide.file_changed", {"path": "tests/test_auth.py"})
        assert len(suggestions) == 1
        assert suggestions[0].payload["skill"] == "test-driven-development"

    def test_correlation_id_chain(self):
        bus = EventBus()
        events = []
        bus.on("*", lambda e: events.append(e))

        bus.emit("injection.completed", {"doc": "a.py"}, correlation_id="chain-1")
        bus.emit("evidence.collected", {"grade": "correlation"}, correlation_id="chain-1")

        assert all(e.metadata.get("correlation_id") == "chain-1" for e in events)

    def test_source_dedup_prevents_echo(self):
        """MCP publish routes through bus; handlers still fire (no source dedup)."""
        bus = EventBus()
        mcp = MCPBridge(bus)
        stream_id = mcp.subscribe(["injection.*"])

        received = []
        bus.on("injection.completed", lambda e: received.append(e))
        mcp.publish("injection.completed", {})

        # Handler fires
        assert len(received) == 1
        # MCP stream also receives it (no dedup — both see the event)
        events = mcp.poll(stream_id)
        assert events is not None
        assert len(events) == 1


class TestE2ETransportChain:

    def test_sse_queues_from_bus(self):
        bus = EventBus()
        sse = SSETransport()
        bus.register_transport(sse)

        bus.emit("health.check", {"status": "ok"})
        events = sse.pending_events()
        assert len(events) == 1

    def test_multiple_transports_all_receive(self, tmp_path):
        bus = EventBus()
        jsonl = JSONLTransport(str(tmp_path / ".events.jsonl"))
        sse = SSETransport()
        bus.register_transport(jsonl)
        bus.register_transport(sse)

        bus.emit("injection.completed", {"doc": "a.py"})

        assert Path(tmp_path / ".events.jsonl").exists()
        assert len(sse.pending_events()) == 1

    def test_event_validation_on_emit(self):
        bus = EventBus()
        event = bus.emit("injection.completed", {})
        assert validate_event_type(event.type) is True

    def test_ring_buffer_survives_high_volume(self):
        bus = EventBus(buffer_size=100)
        for i in range(1000):
            bus.emit("test.event", {"i": i})
        recent = bus.recent_events(10)
        assert len(recent) == 10
        assert recent[-1].payload["i"] == 999
        assert bus.events_dropped == 900
