"""Tests for ide package public API."""
from __future__ import annotations

from three_surgeons.ide.event_bus import EventBus

import pytest


@pytest.fixture(autouse=True)
def reset():
    yield
    EventBus.reset_instance()


class TestPublicAPI:

    def test_imports_event_bus(self):
        from three_surgeons.ide import EventBus
        assert EventBus is not None

    def test_imports_envelope(self):
        from three_surgeons.ide import EventEnvelope
        assert EventEnvelope is not None

    def test_imports_namespace(self):
        from three_surgeons.ide import EventNamespace
        assert EventNamespace is not None

    def test_imports_validate(self):
        from three_surgeons.ide import validate_event_type
        assert validate_event_type is not None

    def test_event_bus_creation_via_package(self):
        from three_surgeons.ide import EventBus
        bus = EventBus()
        assert bus is not None
