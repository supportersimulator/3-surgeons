"""WebSocket transport for EventBus.

Runs an asyncio WebSocket server on 127.0.0.1:8031 (configurable).
Clients subscribe to event patterns and receive matching events as JSON.
Also accepts publish messages from clients (bidirectional).

Uses websockets v16 modern API (ServerConnection, not legacy WebSocketServerProtocol).
Thread-safe: deliver() may be called from any thread; _clients dict
protected by threading.Lock per 3-surgeon cross-exam recommendation.
"""
from __future__ import annotations

import asyncio
import json
import logging
import threading
from dataclasses import asdict
from typing import Any, Dict, Optional, Set

logger = logging.getLogger(__name__)

try:
    import websockets
    from websockets.asyncio.server import Server, ServerConnection, serve
except ImportError:
    websockets = None  # type: ignore[assignment]

from three_surgeons.ide.event_bus import EventBus, EventEnvelope


class WebSocketTransport:
    """WebSocket transport adapter for EventBus.

    Args:
        host: Bind address (default 127.0.0.1, localhost only).
        port: Bind port (default 8031).
        max_connections: Max concurrent WebSocket clients (default 10).
    """

    def __init__(
        self,
        host: str = "127.0.0.1",
        port: int = 8031,
        max_connections: int = 10,
    ) -> None:
        if websockets is None:
            raise ImportError("websockets package required: pip install 'three-surgeons[ide]'")
        self.host = host
        self.port = port
        self.max_connections = max_connections
        self._server: Optional[Server] = None
        self._clients: Dict[ServerConnection, Set[str]] = {}
        self._lock = threading.Lock()
        self._bus: Optional[EventBus] = None
        self._loop: Optional[asyncio.AbstractEventLoop] = None

    @property
    def is_running(self) -> bool:
        return self._server is not None

    async def start(self) -> None:
        self._loop = asyncio.get_running_loop()
        self._server = await serve(
            self._handle_client,
            self.host,
            self.port,
        )
        logger.info("WebSocket transport listening on %s:%d", self.host, self.port)

    async def stop(self) -> None:
        if self._server:
            self._server.close()
            await self._server.wait_closed()
            self._server = None
            with self._lock:
                self._clients.clear()
            logger.info("WebSocket transport stopped")

    async def _handle_client(self, ws: ServerConnection) -> None:
        with self._lock:
            if len(self._clients) >= self.max_connections:
                await ws.close(1013, "Max connections reached")
                return
            self._clients[ws] = set()

        try:
            async for raw in ws:
                try:
                    msg = json.loads(raw)
                    self._handle_message(ws, msg)
                except json.JSONDecodeError:
                    logger.warning("Invalid JSON from client")
        except Exception:
            logger.debug("Client disconnected", exc_info=True)
        finally:
            with self._lock:
                self._clients.pop(ws, None)

    def _handle_message(
        self, ws: ServerConnection, msg: Dict[str, Any]
    ) -> None:
        msg_type = msg.get("type")

        if msg_type == "subscribe":
            patterns = msg.get("patterns", [])
            with self._lock:
                self._clients.setdefault(ws, set()).update(patterns)

        elif msg_type == "unsubscribe":
            patterns = msg.get("patterns", [])
            with self._lock:
                if ws in self._clients:
                    self._clients[ws] -= set(patterns)

        elif msg_type == "publish":
            event_data = msg.get("event", {})
            if self._bus:
                self._bus.emit(
                    event_data.get("type", "unknown"),
                    event_data.get("payload", {}),
                    source="websocket",
                )

    def deliver(self, event: EventEnvelope) -> None:
        """Called by EventBus for each emitted event. Forwards to subscribed clients."""
        if not self._loop:
            return

        # Don't echo back websocket-originated events
        if event.source == "websocket":
            return

        event_dict = {
            "type": "event",
            "event": asdict(event),
        }
        raw = json.dumps(event_dict)

        with self._lock:
            targets = [
                ws for ws, patterns in self._clients.items()
                if self._should_deliver(event.type, patterns)
            ]

        for ws in targets:
            asyncio.run_coroutine_threadsafe(
                self._safe_send(ws, raw), self._loop
            )

    @staticmethod
    def _should_deliver(event_type: str, patterns: Set[str]) -> bool:
        for pattern in patterns:
            if pattern == "*":
                return True
            if pattern.endswith(".*"):
                prefix = pattern[:-2]
                if event_type.startswith(prefix + "."):
                    return True
            elif pattern == event_type:
                return True
        return False

    async def _safe_send(self, ws: ServerConnection, data: str) -> None:
        try:
            await ws.send(data)
        except Exception:
            logger.debug("Failed to send to client", exc_info=True)
            with self._lock:
                self._clients.pop(ws, None)

    def set_bus(self, bus: EventBus) -> None:
        """Set bus reference for publish handling."""
        self._bus = bus
