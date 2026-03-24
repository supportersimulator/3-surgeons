"""Observability adapter — structured event logging to .observability.db."""

from __future__ import annotations

import json
import logging
import os
import sqlite3
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from three_surgeons.adapters._protocol import SurgeryAdapter, Capability

logger = logging.getLogger(__name__)

_DB_DIR = os.path.expanduser("~/.3surgeons")
_DB_PATH = os.path.join(_DB_DIR, "observability.db")


class ObservabilityAdapter(SurgeryAdapter):
    """Structured event logging to a local SQLite database."""

    capabilities = Capability.OBSERVABILITY
    thread_safe = True
    gate_mode = "warn"

    def __init__(self) -> None:
        self._conn: Optional[sqlite3.Connection] = None

    def on_init(self) -> None:
        try:
            os.makedirs(_DB_DIR, exist_ok=True)
            self._conn = sqlite3.connect(_DB_PATH, check_same_thread=False)
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute(
                """CREATE TABLE IF NOT EXISTS events (
                    id INTEGER PRIMARY KEY,
                    timestamp TEXT,
                    event_type TEXT,
                    operation TEXT,
                    data TEXT,
                    surgeon TEXT
                )"""
            )
            self._conn.execute(
                "DELETE FROM events WHERE timestamp < datetime('now', '-30 days')"
            )
            self._conn.commit()
        except Exception as exc:
            logger.debug("ObservabilityAdapter on_init failed: %s", exc)

    def on_cost(self, surgeon: str, cost_usd: float, operation: str) -> None:
        self._insert_event(
            event_type="cost",
            operation=operation,
            data={"surgeon": surgeon, "cost_usd": cost_usd, "operation": operation},
            surgeon=surgeon,
        )

    def on_cross_exam_logged(self, topic: str, data: Dict[str, Any]) -> None:
        self._insert_event(
            event_type="cross_exam",
            operation="cross_exam",
            data={"topic": topic, **data},
        )

    def on_error(self, operation: str, error: Exception, context: Dict[str, Any]) -> None:
        self._insert_event(
            event_type="error",
            operation=operation,
            data={"operation": operation, "error": str(error), "context": context},
        )

    def on_workflow_start(self, operation: str, context: Dict[str, Any]) -> None:
        self._insert_event(
            event_type="workflow_start",
            operation=operation,
            data=context,
        )

    def on_workflow_end(self, operation: str, result: Dict[str, Any]) -> None:
        self._insert_event(
            event_type="workflow_end",
            operation=operation,
            data=result,
        )

    def on_user_action(self, action: str, details: Dict[str, Any]) -> None:
        self._insert_event(
            event_type="user_action",
            operation=action,
            data=details,
        )

    def enrich_topic(self, topic: str) -> str:
        return topic

    def check_gate(self) -> Optional[str]:
        return None

    def close(self) -> None:
        if self._conn is not None:
            try:
                self._conn.close()
            except Exception as exc:
                logger.debug("ObservabilityAdapter close failed: %s", exc)
            finally:
                self._conn = None

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _insert_event(
        self,
        event_type: str,
        operation: str,
        data: Dict[str, Any],
        surgeon: Optional[str] = None,
    ) -> None:
        try:
            if self._conn is None:
                logger.debug("ObservabilityAdapter: DB connection not available")
                return
            self._conn.execute(
                "INSERT INTO events (timestamp, event_type, operation, data, surgeon) "
                "VALUES (?, ?, ?, ?, ?)",
                (
                    datetime.now(timezone.utc).isoformat(),
                    event_type,
                    operation,
                    json.dumps(data),
                    surgeon,
                ),
            )
            self._conn.commit()
        except Exception as exc:
            logger.debug("ObservabilityAdapter insert failed: %s", exc)
