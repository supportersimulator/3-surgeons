"""Tests for JSONL file transport."""
from __future__ import annotations

import json

import pytest

from three_surgeons.ide.event_bus import EventEnvelope
from three_surgeons.ide.transports.jsonl import JSONLTransport


def _make_event(**overrides) -> EventEnvelope:
    defaults = dict(
        id="evt-1",
        version=1,
        type="test.event",
        source="test",
        timestamp="2026-01-01T00:00:00+00:00",
        payload={"key": "value"},
        metadata={},
    )
    defaults.update(overrides)
    return EventEnvelope(**defaults)


class TestJSONLTransport:
    def test_deliver_writes_json_line(self, tmp_path):
        path = tmp_path / "events.jsonl"
        transport = JSONLTransport(str(path))
        event = _make_event()

        transport.deliver(event)

        lines = path.read_text().splitlines()
        assert len(lines) == 1
        parsed = json.loads(lines[0])
        assert parsed["id"] == "evt-1"
        assert parsed["type"] == "test.event"
        assert parsed["payload"] == {"key": "value"}

    def test_multiple_delivers_append(self, tmp_path):
        path = tmp_path / "events.jsonl"
        transport = JSONLTransport(str(path))

        transport.deliver(_make_event(id="evt-1"))
        transport.deliver(_make_event(id="evt-2"))
        transport.deliver(_make_event(id="evt-3"))

        lines = path.read_text().splitlines()
        assert len(lines) == 3
        ids = [json.loads(l)["id"] for l in lines]
        assert ids == ["evt-1", "evt-2", "evt-3"]

    def test_creates_parent_directories(self, tmp_path):
        path = tmp_path / "deep" / "nested" / "dir" / "events.jsonl"
        transport = JSONLTransport(str(path))

        transport.deliver(_make_event())

        assert path.exists()
        assert len(path.read_text().splitlines()) == 1

    def test_rotation_on_size_threshold(self, tmp_path):
        path = tmp_path / "events.jsonl"
        max_bytes = 100
        transport = JSONLTransport(str(path), max_bytes=max_bytes)

        # Write enough to exceed threshold
        for i in range(20):
            transport.deliver(_make_event(id=f"evt-{i}"))

        # File should have been rotated — current file is smaller than total
        assert path.exists()
        rotated = tmp_path / "events.jsonl.old"
        assert rotated.exists()

        # Both files should have content
        rotated_lines = rotated.read_text().splitlines()
        current_lines = path.read_text().splitlines()
        assert len(rotated_lines) > 0
        assert len(current_lines) > 0

        # Current file should be under the size threshold
        assert path.stat().st_size <= max_bytes + 200  # one event can exceed threshold

        # Last event written should be in the current file
        last_current = json.loads(current_lines[-1])
        assert last_current["id"] == "evt-19"
