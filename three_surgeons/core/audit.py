"""Structured audit trail for tool invocations.

Inspired by Superset's agentCommands table pattern.
Append-only JSONL format — one file per day for easy rotation.
"""
from __future__ import annotations

import json
import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


@dataclass
class AuditEntry:
    tool: str
    params: Dict[str, Any]
    status: str  # "success" | "error" | "denied" | "rate_limited"
    entry_id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    timestamp: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    duration_ms: float = 0.0
    error: Optional[str] = None
    parent_id: Optional[str] = None
    user_id: Optional[str] = None
    session_id: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None

    def to_dict(self) -> Dict[str, Any]:
        d = {
            "entry_id": self.entry_id,
            "timestamp": self.timestamp,
            "tool": self.tool,
            "params": self.params,
            "status": self.status,
            "duration_ms": self.duration_ms,
        }
        if self.error:
            d["error"] = self.error
        if self.parent_id:
            d["parent_id"] = self.parent_id
        if self.user_id:
            d["user_id"] = self.user_id
        if self.session_id:
            d["session_id"] = self.session_id
        if self.metadata:
            d["metadata"] = self.metadata
        return d


class AuditTrail:
    """Append-only JSONL audit log with daily rotation."""

    def __init__(self, storage_dir: Optional[str] = None):
        self._dir = Path(storage_dir) if storage_dir else Path.cwd() / ".3s-audit"
        self._dir.mkdir(parents=True, exist_ok=True)

    def _log_path(self) -> Path:
        date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        return self._dir / f"audit-{date}.jsonl"

    def record(self, **kwargs) -> AuditEntry:
        entry = AuditEntry(**kwargs)
        try:
            with open(self._log_path(), "a") as f:
                f.write(json.dumps(entry.to_dict()) + "\n")
        except OSError as exc:
            logger.error("Audit write failed: %s", exc)
        return entry

    def recent(self, limit: int = 50) -> List[Dict[str, Any]]:
        entries: List[Dict[str, Any]] = []
        for log_file in sorted(self._dir.glob("audit-*.jsonl"), reverse=True):
            for line in reversed(log_file.read_text().strip().split("\n")):
                if line:
                    try:
                        entries.append(json.loads(line))
                    except (json.JSONDecodeError, ValueError):
                        logger.warning("Skipping malformed audit line: %s", line[:100])
                        continue
                    if len(entries) >= limit:
                        return entries
        return entries
