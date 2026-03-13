"""Tests for EventBus startup orchestrator."""
from __future__ import annotations

import pytest

from three_surgeons.ide.event_bus import EventBus
from three_surgeons.ide.startup import create_event_bus, EventBusConfig


@pytest.fixture(autouse=True)
def reset_singleton():
    yield
    EventBus.reset_instance()


class TestStartup:

    def test_create_with_defaults(self):
        bus = create_event_bus()
        assert isinstance(bus, EventBus)

    def test_create_with_jsonl_transport(self, tmp_path):
        config = EventBusConfig(
            jsonl_path=str(tmp_path / ".events.jsonl"),
            enable_websocket=False,
        )
        bus = create_event_bus(config)
        assert len(bus._transports) == 1

    def test_create_with_all_transports(self, tmp_path):
        config = EventBusConfig(
            jsonl_path=str(tmp_path / ".events.jsonl"),
            enable_websocket=False,
            enable_sse=True,
        )
        bus = create_event_bus(config)
        assert len(bus._transports) >= 2

    def test_singleton_returns_same_instance(self):
        bus1 = create_event_bus()
        bus2 = create_event_bus()
        assert bus1 is bus2
