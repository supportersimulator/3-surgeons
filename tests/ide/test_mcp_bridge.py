"""Tests for MCP subscription bridge."""
from __future__ import annotations

import time

import pytest

from three_surgeons.ide.event_bus import EventBus, EventEnvelope
from three_surgeons.ide.bridges.mcp_tools import MCPBridge


@pytest.fixture(autouse=True)
def _reset_bus():
    yield
    EventBus.reset_instance()


@pytest.fixture
def bus() -> EventBus:
    return EventBus()


class TestSubscribeAndPoll:
    def test_subscribe_returns_stream_id(self, bus: EventBus) -> None:
        bridge = MCPBridge(bus)
        stream_id = bridge.subscribe(["ide.*"])
        assert isinstance(stream_id, str)
        assert len(stream_id) > 0

    def test_poll_receives_matching_events(self, bus: EventBus) -> None:
        bridge = MCPBridge(bus)
        stream_id = bridge.subscribe(["ide.tool_use_started"])

        bus.emit("ide.tool_use_started", {"tool": "Read"}, source="hook")
        bus.emit("ide.tool_use_started", {"tool": "Bash"}, source="hook")

        events = bridge.poll(stream_id)
        assert events is not None
        assert len(events) == 2
        assert events[0]["payload"]["tool"] == "Read"
        assert events[1]["payload"]["tool"] == "Bash"

    def test_poll_clears_queue(self, bus: EventBus) -> None:
        bridge = MCPBridge(bus)
        stream_id = bridge.subscribe(["ide.notification"])

        bus.emit("ide.notification", {"msg": "hi"}, source="hook")
        first = bridge.poll(stream_id)
        assert len(first) == 1

        second = bridge.poll(stream_id)
        assert second == []

    def test_poll_unknown_stream_returns_none(self, bus: EventBus) -> None:
        bridge = MCPBridge(bus)
        assert bridge.poll("nonexistent") is None

    def test_multiple_patterns(self, bus: EventBus) -> None:
        bridge = MCPBridge(bus)
        stream_id = bridge.subscribe(["ide.notification", "ide.session_ended"])

        bus.emit("ide.notification", {"a": 1}, source="hook")
        bus.emit("ide.session_ended", {"b": 2}, source="hook")
        bus.emit("ide.tool_use_started", {"c": 3}, source="hook")  # not subscribed

        events = bridge.poll(stream_id)
        assert len(events) == 2
        types = {e["type"] for e in events}
        assert types == {"ide.notification", "ide.session_ended"}


class TestPublish:
    def test_publish_emits_event(self, bus: EventBus) -> None:
        bridge = MCPBridge(bus)
        received: list[EventEnvelope] = []
        bus.on("custom.event", received.append)

        event_id = bridge.publish("custom.event", {"key": "val"})

        assert isinstance(event_id, str)
        assert len(received) == 1
        assert received[0].source == "mcp"
        assert received[0].payload == {"key": "val"}

    def test_publish_with_correlation_id(self, bus: EventBus) -> None:
        bridge = MCPBridge(bus)
        received: list[EventEnvelope] = []
        bus.on("x.y", received.append)

        bridge.publish("x.y", {}, correlation_id="corr-123")

        assert received[0].metadata.get("correlation_id") == "corr-123"


class TestUnsubscribe:
    def test_unsubscribe_stops_delivery(self, bus: EventBus) -> None:
        bridge = MCPBridge(bus)
        stream_id = bridge.subscribe(["ide.notification"])

        bridge.unsubscribe(stream_id)
        bus.emit("ide.notification", {"x": 1}, source="hook")

        assert bridge.poll(stream_id) is None  # stream gone

    def test_unsubscribe_unknown_returns_false(self, bus: EventBus) -> None:
        bridge = MCPBridge(bus)
        assert bridge.unsubscribe("bogus") is False


class TestTTLCleanup:
    def test_cleanup_removes_stale_streams(self, bus: EventBus) -> None:
        bridge = MCPBridge(bus, ttl_seconds=0)  # instant expiry
        stream_id = bridge.subscribe(["ide.*"])

        # Force staleness by ensuring monotonic time has advanced
        time.sleep(0.01)
        removed = bridge.cleanup_stale()

        assert removed == 1
        assert bridge.poll(stream_id) is None  # stream gone

    def test_cleanup_keeps_fresh_streams(self, bus: EventBus) -> None:
        bridge = MCPBridge(bus, ttl_seconds=300)
        stream_id = bridge.subscribe(["ide.*"])

        removed = bridge.cleanup_stale()

        assert removed == 0
        assert bridge.poll(stream_id) is not None  # still alive

    def test_poll_refreshes_ttl(self, bus: EventBus) -> None:
        bridge = MCPBridge(bus, ttl_seconds=1)
        stream_id = bridge.subscribe(["ide.*"])

        # Poll refreshes the timer
        bridge.poll(stream_id)
        removed = bridge.cleanup_stale()

        assert removed == 0
