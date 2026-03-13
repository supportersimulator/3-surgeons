"""Tests for EventBus core — pub/sub, wildcard, ring buffer."""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from three_surgeons.ide.event_bus import EventBus


@pytest.fixture(autouse=True)
def _reset():
    yield
    EventBus.reset_instance()


class TestEventBusSubscription:

    def test_on_receives_exact_match(self):
        bus = EventBus()
        received = []
        bus.on("injection.completed", lambda e: received.append(e))
        bus.emit("injection.completed", {"doc": "foo.py"})
        assert len(received) == 1
        assert received[0].payload == {"doc": "foo.py"}

    def test_on_ignores_non_matching(self):
        bus = EventBus()
        received = []
        bus.on("injection.completed", lambda e: received.append(e))
        bus.emit("injection.failed", {"error": "timeout"})
        assert len(received) == 0

    def test_off_removes_handler(self):
        bus = EventBus()
        received = []
        handler = lambda e: received.append(e)
        bus.on("injection.completed", handler)
        bus.off("injection.completed", handler)
        bus.emit("injection.completed", {})
        assert len(received) == 0

    def test_once_fires_only_once(self):
        bus = EventBus()
        received = []
        bus.once("health.check", lambda e: received.append(e))
        bus.emit("health.check", {})
        bus.emit("health.check", {})
        assert len(received) == 1


class TestEventBusWildcard:

    def test_star_matches_namespace(self):
        bus = EventBus()
        received = []
        bus.on("injection.*", lambda e: received.append(e))
        bus.emit("injection.completed", {})
        bus.emit("injection.failed", {})
        bus.emit("health.check", {})
        assert len(received) == 2

    def test_global_star_matches_all(self):
        bus = EventBus()
        received = []
        bus.on("*", lambda e: received.append(e))
        bus.emit("injection.completed", {})
        bus.emit("health.check", {})
        assert len(received) == 2

    def test_partial_wildcard(self):
        bus = EventBus()
        received = []
        bus.on("surgeon.*", lambda e: received.append(e))
        bus.emit("surgeon.cross_exam_started", {})
        bus.emit("injection.completed", {})
        assert len(received) == 1


class TestEventBusRingBuffer:

    def test_recent_events_returns_last_n(self):
        bus = EventBus(buffer_size=5)
        for i in range(10):
            bus.emit("test.event", {"i": i})
        recent = bus.recent_events(3)
        assert len(recent) == 3
        assert recent[0].payload == {"i": 7}

    def test_buffer_overflow_increments_counter(self):
        bus = EventBus(buffer_size=3)
        for i in range(5):
            bus.emit("test.event", {"i": i})
        assert bus.events_dropped == 2


class TestEventBusCorrelation:

    def test_emit_with_correlation_id(self):
        bus = EventBus()
        received = []
        bus.on("injection.*", lambda e: received.append(e))
        bus.emit("injection.completed", {}, correlation_id="abc-123")
        assert received[0].metadata.get("correlation_id") == "abc-123"

    def test_emit_with_source(self):
        bus = EventBus()
        received = []
        bus.on("injection.*", lambda e: received.append(e))
        bus.emit("injection.completed", {}, source="typescript")
        assert received[0].source == "typescript"


class TestEventBusErrorIsolation:

    def test_bad_handler_does_not_block_others(self):
        bus = EventBus()
        received = []

        def bad_handler(e):
            raise RuntimeError("boom")

        bus.on("test.event", bad_handler)
        bus.on("test.event", lambda e: received.append(e))
        bus.emit("test.event", {})
        assert len(received) == 1


class TestEventBusTransport:

    def test_register_transport(self):
        bus = EventBus()
        transport = MagicMock()
        transport.deliver = MagicMock()
        bus.register_transport(transport)
        bus.emit("test.event", {})
        transport.deliver.assert_called_once()

    def test_transport_error_does_not_crash_bus(self):
        bus = EventBus()
        transport = MagicMock()
        transport.deliver = MagicMock(side_effect=RuntimeError("fail"))
        bus.register_transport(transport)
        received = []
        bus.on("test.event", lambda e: received.append(e))
        bus.emit("test.event", {})
        assert len(received) == 1


class TestEventBusSingleton:

    def test_get_instance_returns_same(self):
        a = EventBus.get_instance()
        b = EventBus.get_instance()
        assert a is b

    def test_reset_clears_singleton(self):
        a = EventBus.get_instance()
        EventBus.reset_instance()
        b = EventBus.get_instance()
        assert a is not b
