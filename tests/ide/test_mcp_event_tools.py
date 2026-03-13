"""Tests for MCP event subscription tools."""
from __future__ import annotations

import pytest

from three_surgeons.ide.event_bus import EventBus
from three_surgeons.mcp.event_tools import (
    event_poll,
    event_publish,
    event_subscribe,
    event_unsubscribe,
)


@pytest.fixture(autouse=True)
def _reset():
    yield
    EventBus.reset_instance()
    from three_surgeons.mcp.event_tools import _reset_streams

    _reset_streams()


@pytest.fixture
def bus() -> EventBus:
    return EventBus()


class TestEventSubscribe:
    def test_returns_stream_id_and_patterns(self, bus: EventBus) -> None:
        result = event_subscribe(bus, ["file.saved"])
        assert "stream_id" in result
        assert result["patterns"] == ["file.saved"]

    def test_multiple_patterns(self, bus: EventBus) -> None:
        result = event_subscribe(bus, ["file.saved", "file.opened", "diag.*"])
        assert result["patterns"] == ["file.saved", "file.opened", "diag.*"]
        assert "stream_id" in result


class TestEventUnsubscribe:
    def test_removes_stream(self, bus: EventBus) -> None:
        sub = event_subscribe(bus, ["file.saved"])
        result = event_unsubscribe(bus, sub["stream_id"])
        assert result == {"removed": True}

    def test_unknown_stream(self, bus: EventBus) -> None:
        result = event_unsubscribe(bus, "nonexistent-id")
        assert result["removed"] is False
        assert "reason" in result


class TestEventPublish:
    def test_emits_event(self, bus: EventBus) -> None:
        received = []
        bus.on("test.event", lambda e: received.append(e))

        result = event_publish(bus, "test.event", payload={"key": "value"})

        assert result["emitted"] is True
        assert "event_id" in result
        assert len(received) == 1
        assert received[0].payload == {"key": "value"}
        assert received[0].source == "mcp"


class TestEventPoll:
    def test_returns_pending_events(self, bus: EventBus) -> None:
        sub = event_subscribe(bus, ["file.saved"])
        bus.emit("file.saved", {"path": "a.py"}, source="ide")
        bus.emit("file.saved", {"path": "b.py"}, source="ide")

        result = event_poll(bus, sub["stream_id"])

        assert len(result["events"]) == 2
        assert result["events"][0]["payload"]["path"] == "a.py"
        assert result["events"][1]["payload"]["path"] == "b.py"

    def test_clears_after_read(self, bus: EventBus) -> None:
        sub = event_subscribe(bus, ["file.saved"])
        bus.emit("file.saved", {"path": "a.py"}, source="ide")

        first = event_poll(bus, sub["stream_id"])
        assert len(first["events"]) == 1

        second = event_poll(bus, sub["stream_id"])
        assert len(second["events"]) == 0

    def test_unknown_stream(self, bus: EventBus) -> None:
        result = event_poll(bus, "nonexistent-id")
        assert result["events"] == []
        assert "error" in result
