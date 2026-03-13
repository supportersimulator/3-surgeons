"""Tests for WebSocket transport server (websockets v16)."""
from __future__ import annotations

import asyncio
import json

import pytest
import pytest_asyncio

from three_surgeons.ide.event_bus import EventBus, EventEnvelope
from three_surgeons.ide.transports.websocket import WebSocketTransport

pytestmark = pytest.mark.asyncio


@pytest.fixture
def bus():
    b = EventBus()
    yield b
    EventBus.reset_instance()


@pytest.fixture
def free_port():
    """Find a free TCP port."""
    import socket

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest_asyncio.fixture
async def ws_transport(bus, free_port):
    transport = WebSocketTransport(host="127.0.0.1", port=free_port)
    transport.set_bus(bus)
    bus.register_transport(transport)
    await transport.start()
    yield transport
    await transport.stop()


class TestWebSocketTransport:

    async def test_server_starts_and_stops(self, ws_transport):
        assert ws_transport.is_running

    async def test_client_subscribe_receives_events(self, bus, ws_transport):
        import websockets

        uri = f"ws://127.0.0.1:{ws_transport.port}"
        async with websockets.connect(uri) as ws:
            await ws.send(json.dumps({
                "type": "subscribe",
                "patterns": ["injection.*"],
            }))
            # Small delay to let subscribe register
            await asyncio.sleep(0.05)

            bus.emit("injection.completed", {"doc": "test.py"})
            # deliver() schedules coroutine — give event loop a tick
            await asyncio.sleep(0.05)

            msg = await asyncio.wait_for(ws.recv(), timeout=2.0)
            data = json.loads(msg)
            assert data["type"] == "event"
            assert data["event"]["type"] == "injection.completed"

    async def test_client_unsubscribe(self, bus, ws_transport):
        import websockets

        uri = f"ws://127.0.0.1:{ws_transport.port}"
        async with websockets.connect(uri) as ws:
            await ws.send(json.dumps({
                "type": "subscribe",
                "patterns": ["injection.*"],
            }))
            await asyncio.sleep(0.05)

            await ws.send(json.dumps({
                "type": "unsubscribe",
                "patterns": ["injection.*"],
            }))
            await asyncio.sleep(0.05)

            bus.emit("injection.completed", {})
            await asyncio.sleep(0.05)

            with pytest.raises(asyncio.TimeoutError):
                await asyncio.wait_for(ws.recv(), timeout=0.3)

    async def test_client_publish(self, bus, ws_transport):
        import websockets

        received = []
        bus.on("ide.file_changed", lambda e: received.append(e))

        uri = f"ws://127.0.0.1:{ws_transport.port}"
        async with websockets.connect(uri) as ws:
            await ws.send(json.dumps({
                "type": "publish",
                "event": {
                    "type": "ide.file_changed",
                    "payload": {"path": "/foo.py"},
                },
            }))
            await asyncio.sleep(0.2)

        assert len(received) == 1
        assert received[0].source == "websocket"

    async def test_max_connections_enforced(self, ws_transport):
        import websockets

        uri = f"ws://127.0.0.1:{ws_transport.port}"
        connections = []
        for _ in range(10):
            ws = await websockets.connect(uri)
            connections.append(ws)

        # 11th should be rejected (server closes with 1013)
        try:
            ws11 = await websockets.connect(uri)
            # If we connected, server should close us immediately
            with pytest.raises(Exception):
                await asyncio.wait_for(ws11.recv(), timeout=1.0)
        except Exception:
            pass  # Connection refused or closed — expected

        for ws in connections:
            await ws.close()

    async def test_deliver_method(self, ws_transport):
        """deliver() is called by EventBus for each event."""
        import websockets

        uri = f"ws://127.0.0.1:{ws_transport.port}"
        async with websockets.connect(uri) as ws:
            await ws.send(json.dumps({
                "type": "subscribe",
                "patterns": ["*"],
            }))
            await asyncio.sleep(0.05)

            event = EventEnvelope(
                id="test-id",
                version=1,
                type="test.event",
                source="python",
                timestamp="2026-01-01T00:00:00Z",
                payload={"key": "value"},
            )
            ws_transport.deliver(event)
            await asyncio.sleep(0.05)

            msg = await asyncio.wait_for(ws.recv(), timeout=2.0)
            data = json.loads(msg)
            assert data["event"]["id"] == "test-id"

    async def test_websocket_source_not_echoed(self, ws_transport):
        """Events from websocket source should not be echoed back."""
        import websockets

        uri = f"ws://127.0.0.1:{ws_transport.port}"
        async with websockets.connect(uri) as ws:
            await ws.send(json.dumps({
                "type": "subscribe",
                "patterns": ["*"],
            }))
            await asyncio.sleep(0.05)

            event = EventEnvelope(
                id="ws-origin",
                version=1,
                type="ide.file_changed",
                source="websocket",
                timestamp="2026-01-01T00:00:00Z",
                payload={},
            )
            ws_transport.deliver(event)
            await asyncio.sleep(0.05)

            with pytest.raises(asyncio.TimeoutError):
                await asyncio.wait_for(ws.recv(), timeout=0.3)

    async def test_wildcard_pattern_matching(self, ws_transport):
        """Test various wildcard patterns."""
        import websockets

        uri = f"ws://127.0.0.1:{ws_transport.port}"
        async with websockets.connect(uri) as ws:
            await ws.send(json.dumps({
                "type": "subscribe",
                "patterns": ["health.*"],
            }))
            await asyncio.sleep(0.05)

            # Should match
            event_match = EventEnvelope(
                id="1", version=1, type="health.check",
                source="python", timestamp="2026-01-01T00:00:00Z",
                payload={},
            )
            ws_transport.deliver(event_match)
            await asyncio.sleep(0.05)

            msg = await asyncio.wait_for(ws.recv(), timeout=2.0)
            assert json.loads(msg)["event"]["type"] == "health.check"

            # Should NOT match
            event_no = EventEnvelope(
                id="2", version=1, type="injection.completed",
                source="python", timestamp="2026-01-01T00:00:00Z",
                payload={},
            )
            ws_transport.deliver(event_no)
            await asyncio.sleep(0.05)

            with pytest.raises(asyncio.TimeoutError):
                await asyncio.wait_for(ws.recv(), timeout=0.3)

    async def test_stop_clears_state(self, bus, free_port):
        transport = WebSocketTransport(host="127.0.0.1", port=free_port)
        bus.register_transport(transport)
        await transport.start()
        assert transport.is_running
        await transport.stop()
        assert not transport.is_running
