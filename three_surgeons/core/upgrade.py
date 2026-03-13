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

import logging

import yaml
import httpx

from three_surgeons.core.config import Config, detect_local_backend

logger = logging.getLogger(__name__)


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

    def __init__(
        self,
        timeout: float = 2.0,
        config_resolver: Optional["ConfigResolver"] = None,
    ) -> None:
        self._timeout = timeout
        self._config_resolver = config_resolver

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
        """Ping Redis. Uses resolver's URL if available, else default port."""
        url = "redis://127.0.0.1:6379/0"
        if self._config_resolver:
            state = self._config_resolver.resolve_state()
            if state.backend == "redis":
                url = state.redis_url
        try:
            import redis
            client = redis.Redis.from_url(url, socket_timeout=self._timeout)
            return client.ping()
        except Exception:
            logger.debug("Redis probe failed", exc_info=True)
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
            logger.debug("ContextDNA probe failed", exc_info=True)
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


class UpgradeAction(enum.Enum):
    """Possible upgrade decisions."""

    SILENT_UPGRADE = "silent_upgrade"
    INTERACTIVE_CHOOSER = "interactive_chooser"
    NO_ACTION = "no_action"
    SILENT_DOWNGRADE = "silent_downgrade"


# Phase 2 capabilities — any ONE of these triggers Phase 2
_PHASE2_CAPABILITIES = {InfraCapability.REDIS, InfraCapability.CONTEXTDNA}


class UpgradeEngine:
    """Orchestrates probe -> decide -> execute upgrade flow.

    On init, checks for crash recovery (interrupted transactions).
    """

    def __init__(self, config: Config, config_dir: Path) -> None:
        self._config = config
        self._config_dir = config_dir
        self._config_path = config_dir / "config.yaml"
        self._event_log = UpgradeEventLog(config_dir / "upgrade.log")
        self.recovered_from_crash = False

        # Crash recovery check
        tx = UpgradeTransaction(config_dir)
        if tx.needs_recovery():
            recovery_info = tx.recover()
            self.recovered_from_crash = True
            if recovery_info:
                self._config.phase = recovery_info.get("from_phase", 1)
                self._event_log.record(
                    "crash_recovery",
                    from_phase=recovery_info.get("to_phase"),
                    to_phase=recovery_info.get("from_phase"),
                    details="Recovered from interrupted upgrade",
                )

    def decide(self, probe_result: ProbeResult) -> tuple:
        """Decide upgrade action based on probe results.

        Returns (UpgradeAction, details_dict).
        """
        current = self._config.phase
        detected = probe_result.detected_phase

        if detected == current:
            return UpgradeAction.NO_ACTION, {}

        if detected < current:
            # Degradation detected
            return UpgradeAction.SILENT_DOWNGRADE, {
                "target_phase": detected,
                "reason": "Infrastructure no longer available",
            }

        # Upgrade available — check if multiple Phase 2 paths exist
        phase2_caps = [c for c in probe_result.capabilities if c in _PHASE2_CAPABILITIES]
        if len(phase2_caps) > 1 and current < 2:
            return UpgradeAction.INTERACTIVE_CHOOSER, {
                "target_phase": detected,
                "options": [c.value for c in phase2_caps],
            }

        return UpgradeAction.SILENT_UPGRADE, {"target_phase": detected}

    def execute_upgrade(self, target_phase: int) -> None:
        """Execute an upgrade transaction to target_phase."""
        current = self._config.phase
        tx = UpgradeTransaction(self._config_dir)

        # 1. Begin transaction (snapshot)
        tx.begin(current_phase=current, target_phase=target_phase)

        try:
            # 2. Apply config changes
            config_data = {}
            if self._config_path.is_file():
                config_data = yaml.safe_load(self._config_path.read_text()) or {}
            config_data["phase"] = target_phase
            self._config_path.write_text(yaml.dump(config_data, default_flow_style=False))

            # 3. Commit transaction
            tx.commit()
            self._config.phase = target_phase

            # 4. Log event
            event = "upgrade" if target_phase > current else "downgrade"
            self._event_log.record(event, from_phase=current, to_phase=target_phase)

        except Exception:
            # Rollback on any failure — guard against rollback itself failing
            try:
                tx.rollback()
            except Exception:
                logger.error("Rollback failed during upgrade recovery", exc_info=True)
            self._event_log.record(
                "upgrade_failed",
                from_phase=current,
                to_phase=target_phase,
                details="Rolled back due to error",
            )
            raise


class AdaptivePoller:
    """Adaptive polling interval: starts fast, backs off when stable.

    Starts at base_interval (default 5min/300s), backs off by 1.5x
    on each no-change probe, caps at max_interval (default 1hr/3600s).
    Resets to base_interval on any system change signal.
    """

    def __init__(
        self,
        base_interval: int = 300,
        max_interval: int = 3600,
        backoff_factor: float = 1.5,
    ) -> None:
        self.base_interval = base_interval
        self.max_interval = max_interval
        self._backoff_factor = backoff_factor
        self.current_interval: float = base_interval
        self._last_probe: Optional[float] = None

    def on_no_change(self) -> None:
        """Called when probe finds no changes. Increase interval."""
        self.current_interval = min(
            self.current_interval * self._backoff_factor,
            self.max_interval,
        )

    def on_change_detected(self) -> None:
        """Called when any system change is detected. Reset interval."""
        self.current_interval = self.base_interval

    def should_probe(self) -> bool:
        """True if enough time has passed since last probe."""
        if self._last_probe is None:
            return True
        return (time.time() - self._last_probe) >= self.current_interval

    def mark_probed(self) -> None:
        """Record that a probe just ran."""
        self._last_probe = time.time()


class NudgeDetector:
    """Detects when a user would benefit from upgrading.

    Thresholds indicate a power user who would benefit from
    shared state and expanded queue backends.
    """

    EVIDENCE_THRESHOLD = 50
    CROSS_EXAM_THRESHOLD = 10
    CONFIG_EDIT_THRESHOLD = 5

    def __init__(
        self,
        evidence_count: int = 0,
        cross_exam_count: int = 0,
        config_edit_count: int = 0,
        nudge_enabled: bool = True,
    ) -> None:
        self._evidence_count = evidence_count
        self._cross_exam_count = cross_exam_count
        self._config_edit_count = config_edit_count
        self._nudge_enabled = nudge_enabled

    def should_nudge(self) -> bool:
        """True if any threshold is exceeded and nudge is enabled."""
        if not self._nudge_enabled:
            return False
        return (
            self._evidence_count > self.EVIDENCE_THRESHOLD
            or self._cross_exam_count > self.CROSS_EXAM_THRESHOLD
            or self._config_edit_count > self.CONFIG_EDIT_THRESHOLD
        )

    def reason(self) -> str:
        """Human-readable reason for nudge."""
        reasons = []
        if self._evidence_count > self.EVIDENCE_THRESHOLD:
            reasons.append(f"{self._evidence_count} evidence items (>{self.EVIDENCE_THRESHOLD})")
        if self._cross_exam_count > self.CROSS_EXAM_THRESHOLD:
            reasons.append(f"{self._cross_exam_count} cross-exams (>{self.CROSS_EXAM_THRESHOLD})")
        if self._config_edit_count > self.CONFIG_EDIT_THRESHOLD:
            reasons.append(f"{self._config_edit_count} config edits (>{self.CONFIG_EDIT_THRESHOLD})")
        return "Power user thresholds reached: " + ", ".join(reasons) if reasons else ""
