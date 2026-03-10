# three_surgeons/core/upgrade.py
"""Upgrade adaptability engine.

Detects ecosystem state, manages upgrade transactions, handles
crash recovery, and orchestrates phase transitions.
"""
from __future__ import annotations

import enum
import hashlib
import json
import os
import time
from datetime import datetime, timezone
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

import httpx

from three_surgeons.core.config import Config, detect_local_backend


class InfraCapability(enum.Enum):
    """Detectable infrastructure capabilities."""

    LOCAL_LLM = "local_llm"
    REDIS = "redis"
    CONTEXTDNA = "contextdna"
    IDE_EVENT_BUS = "ide_event_bus"


@dataclass
class ProbeResult:
    """Result of an ecosystem probe."""

    detected_phase: int = 1
    capabilities: List[InfraCapability] = field(default_factory=list)
    details: Dict[str, Any] = field(default_factory=dict)
    timestamp: float = field(default_factory=time.time)


class EcosystemProbe:
    """Probes the local environment for available infrastructure.

    Checks: local LLMs, Redis, ContextDNA adapter, IDE event bus.
    Determines the highest phase the system can support.
    """

    def __init__(self, timeout: float = 2.0) -> None:
        self._timeout = timeout

    def run(self) -> ProbeResult:
        """Run all probes and determine detected phase."""
        result = ProbeResult()

        # Check local LLM backends
        backends = detect_local_backend(timeout_s=self._timeout)
        if backends:
            result.capabilities.append(InfraCapability.LOCAL_LLM)
            result.details["local_backends"] = [b["provider"] for b in backends]

        # Check Redis
        if self._check_redis():
            result.capabilities.append(InfraCapability.REDIS)

        # Check ContextDNA
        if self._check_contextdna():
            result.capabilities.append(InfraCapability.CONTEXTDNA)

        # Check IDE event bus
        if self._check_ide_event_bus():
            result.capabilities.append(InfraCapability.IDE_EVENT_BUS)

        # Determine phase
        if InfraCapability.IDE_EVENT_BUS in result.capabilities:
            result.detected_phase = 3
        elif (InfraCapability.REDIS in result.capabilities
              or InfraCapability.CONTEXTDNA in result.capabilities):
            result.detected_phase = 2
        else:
            result.detected_phase = 1

        return result

    def _check_redis(self) -> bool:
        """Ping Redis on default port."""
        try:
            import redis
            client = redis.Redis(host="127.0.0.1", port=6379, socket_timeout=self._timeout)
            return client.ping()
        except Exception:
            return False

    def _check_contextdna(self) -> bool:
        """Check for ContextDNA adapter (env var or port 8029)."""
        if os.environ.get("CONTEXTDNA_ADAPTER"):
            return True
        try:
            resp = httpx.get(
                "http://127.0.0.1:8029/health",
                timeout=self._timeout,
            )
            return resp.status_code == 200
        except Exception:
            return False

    def _check_ide_event_bus(self) -> bool:
        """Check for IDE event bus (future -- Phase 3)."""
        # Phase 3: check for Electron IPC or event bus socket
        return os.environ.get("CONTEXTDNA_IDE_BUS") is not None


class ConfigTracker:
    """Tracks config file changes via SHA256 hash + monotonic sequence."""

    def __init__(self, config_path: Path) -> None:
        self._path = config_path
        self._stored_hash: Optional[str] = None
        self.sequence: int = 0

    def compute_hash(self) -> Optional[str]:
        """SHA256 of config file contents. None if file missing."""
        if not self._path.is_file():
            return None
        content = self._path.read_bytes()
        return hashlib.sha256(content).hexdigest()

    def update_stored_hash(self) -> None:
        """Store current hash as reference for change detection."""
        self._stored_hash = self.compute_hash()

    def has_changed(self) -> bool:
        """True if config file changed since last update_stored_hash()."""
        return self.compute_hash() != self._stored_hash

    def increment_sequence(self) -> int:
        """Increment and return monotonic sequence counter."""
        self.sequence += 1
        return self.sequence


class TransactionStatus(enum.Enum):
    """Upgrade transaction status."""

    IN_PROGRESS = "in_progress"
    COMMITTED = "committed"


class UpgradeTransaction:
    """Atomic upgrade transaction with crash recovery.

    Every upgrade is a transaction:
    1. begin() — snapshot current config, mark "in_progress"
    2. (caller applies config changes)
    3. commit() — mark "committed"

    On startup, if snapshot status == "in_progress":
    → Crash detected → auto-revert to snapshot state.
    """

    SNAPSHOT_FILE = "upgrade_snapshot.json"

    def __init__(self, config_dir: Path) -> None:
        self._config_dir = config_dir
        self._snapshot_path = config_dir / self.SNAPSHOT_FILE
        self._config_path = config_dir / "config.yaml"
        self.status: Optional[TransactionStatus] = None

        # Load existing snapshot status if present
        if self._snapshot_path.is_file():
            try:
                data = json.loads(self._snapshot_path.read_text())
                status_str = data.get("status")
                if status_str == "in_progress":
                    self.status = TransactionStatus.IN_PROGRESS
                elif status_str == "committed":
                    self.status = TransactionStatus.COMMITTED
            except (json.JSONDecodeError, KeyError):
                pass

    def begin(self, current_phase: int, target_phase: int) -> None:
        """Start an upgrade transaction. Snapshots current config."""
        config_content = ""
        if self._config_path.is_file():
            config_content = self._config_path.read_text()

        snapshot = {
            "status": "in_progress",
            "from_phase": current_phase,
            "to_phase": target_phase,
            "config_backup": config_content,
            "timestamp": time.time(),
        }
        self._snapshot_path.write_text(json.dumps(snapshot, indent=2))
        self.status = TransactionStatus.IN_PROGRESS

    def commit(self) -> None:
        """Mark transaction as committed (upgrade succeeded)."""
        if not self._snapshot_path.is_file():
            return
        data = json.loads(self._snapshot_path.read_text())
        data["status"] = "committed"
        self._snapshot_path.write_text(json.dumps(data, indent=2))
        self.status = TransactionStatus.COMMITTED

    def rollback(self) -> None:
        """Revert config to pre-upgrade state and remove snapshot."""
        if not self._snapshot_path.is_file():
            return
        data = json.loads(self._snapshot_path.read_text())
        config_backup = data.get("config_backup", "")
        if config_backup:
            self._config_path.write_text(config_backup)
        self._snapshot_path.unlink(missing_ok=True)
        self.status = None

    def needs_recovery(self) -> bool:
        """True if a previous upgrade was interrupted (crash)."""
        return self.status == TransactionStatus.IN_PROGRESS

    def recover(self) -> Optional[dict]:
        """Auto-recover from interrupted upgrade. Returns snapshot info or None."""
        if not self.needs_recovery():
            return None
        data = json.loads(self._snapshot_path.read_text())
        self.rollback()
        return data


class UpgradeEventLog:
    """Append-only, human-readable upgrade event log.

    Every upgrade, downgrade, revert, and probe result writes here.
    Accessed via: 3s doctor --history
    """

    def __init__(self, log_path: Path) -> None:
        self._path = log_path

    def record(
        self,
        event: str,
        from_phase: Optional[int] = None,
        to_phase: Optional[int] = None,
        details: Optional[str] = None,
    ) -> None:
        """Append a timestamped event entry."""
        entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "event": event,
        }
        if from_phase is not None:
            entry["from_phase"] = from_phase
        if to_phase is not None:
            entry["to_phase"] = to_phase
        if details:
            entry["details"] = details

        self._path.parent.mkdir(parents=True, exist_ok=True)
        with open(self._path, "a") as f:
            f.write(json.dumps(entry) + "\n")

    def read_all(self) -> List[dict]:
        """Read all log entries. Returns list of dicts."""
        if not self._path.is_file():
            return []
        entries = []
        for line in self._path.read_text().splitlines():
            line = line.strip()
            if line:
                try:
                    entries.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
        return entries
