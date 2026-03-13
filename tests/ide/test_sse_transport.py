"""Tests for SSE fallback transport."""
import json

from three_surgeons.ide.event_bus import EventEnvelope
from three_surgeons.ide.transports.sse import SSETransport


def _make_event(event_type: str = "test.event", seq: int = 0) -> EventEnvelope:
    return EventEnvelope(
        id=f"evt-{seq}",
        version=1,
        type=event_type,
        source="test",
        timestamp="2026-03-12T00:00:00+00:00",
        payload={"seq": seq},
        metadata={},
    )


class TestSSETransportDeliver:
    def test_deliver_appends_to_queue(self) -> None:
        transport = SSETransport()
        event = _make_event()
        transport.deliver(event)
        assert len(transport._queue) == 1
        assert transport._queue[0] is event

    def test_deliver_multiple_preserves_order(self) -> None:
        transport = SSETransport()
        events = [_make_event(seq=i) for i in range(5)]
        for e in events:
            transport.deliver(e)
        assert list(transport._queue) == events


class TestSSETransportPendingEvents:
    def test_pending_events_returns_all_and_clears(self) -> None:
        transport = SSETransport()
        events = [_make_event(seq=i) for i in range(3)]
        for e in events:
            transport.deliver(e)

        pending = transport.pending_events()
        assert pending == events
        assert len(transport._queue) == 0

    def test_pending_events_empty_queue(self) -> None:
        transport = SSETransport()
        assert transport.pending_events() == []


class TestSSETransportMaxQueue:
    def test_max_queue_drops_oldest(self) -> None:
        transport = SSETransport(max_queue=3)
        for i in range(5):
            transport.deliver(_make_event(seq=i))

        # Only last 3 should remain (seq 2, 3, 4)
        pending = transport.pending_events()
        assert len(pending) == 3
        assert [e.payload["seq"] for e in pending] == [2, 3, 4]


class TestSSETransportFormatSSE:
    def test_format_sse_structure(self) -> None:
        transport = SSETransport()
        event = _make_event(seq=42)
        result = transport.format_sse(event)

        assert result.startswith("data: ")
        assert result.endswith("\n\n")

    def test_format_sse_valid_json(self) -> None:
        transport = SSETransport()
        event = _make_event(event_type="gate.passed", seq=1)
        result = transport.format_sse(event)

        json_str = result.removeprefix("data: ").rstrip("\n")
        parsed = json.loads(json_str)
        assert parsed["type"] == "gate.passed"
        assert parsed["id"] == "evt-1"
        assert parsed["payload"] == {"seq": 1}
        assert parsed["version"] == 1
        assert parsed["source"] == "test"
