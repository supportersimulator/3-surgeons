"""Capability Registry — per-capability level tracking with Posture state machine.

Tracks 8 capabilities at L1/L2/L3 independently. Emits CapabilityChange
events on transitions. Implements Phase 9 C6 Posture state machine.

Design: docs/plans/2026-03-13-capability-registry-design.md
"""
from __future__ import annotations

import enum
import json
import logging
from dataclasses import dataclass
from typing import Dict, List, Optional


class Capability(enum.Enum):
    """The 8 independently-tracked capabilities."""

    EVIDENCE_STORE = "evidence_store"
    CROSS_EXAM = "cross_exam"
    STATE_BACKEND = "state_backend"
    SKILL_SUGGESTIONS = "skill_suggestions"
    PROJECT_MEMORY = "project_memory"
    HEALTH_MONITORING = "health_monitoring"
    LLM_BACKEND = "llm_backend"
    EVENT_BUS = "event_bus"


class Posture(enum.Enum):
    """Overall system health posture (Phase 9 C6)."""

    NOMINAL = "nominal"
    DEGRADED = "degraded"
    RECOVERING = "recovering"
    RESTORED = "restored"
    SAFE_MODE = "safe_mode"


@dataclass
class CapabilityChange:
    """Record of a single capability level change."""

    capability: str
    old_level: int
    new_level: int
    reason: str
    user_summary: str
    recovery_hint: str

    @property
    def is_upgrade(self) -> bool:
        return self.new_level > self.old_level


logger = logging.getLogger(__name__)


class CapabilityRegistry:
    """Per-capability level tracking with diff detection.

    Each of 8 capabilities is tracked at L1 (standalone), L2 (enhanced),
    or L3 (full suite). Changes are captured as CapabilityChange events
    and cleared on read (diff-then-clear pattern).
    """

    RECOVERY_PROBES_REQUIRED = 3

    def __init__(
        self,
        event_log: Optional["UpgradeEventLog"] = None,
        event_bus: Optional["EventBus"] = None,
    ) -> None:
        self._state: Dict[Capability, int] = {cap: 1 for cap in Capability}
        self._previous: Dict[Capability, int] = {cap: 1 for cap in Capability}
        self._pending_changes: List[CapabilityChange] = []
        self._posture = Posture.NOMINAL
        self._consecutive_healthy = 0
        self._event_log = event_log
        self._event_bus = event_bus
        self._batch_posture = False

    @property
    def posture(self) -> Posture:
        return self._posture

    def get_level(self, capability: Capability) -> int:
        return self._state[capability]

    def set_level(
        self,
        capability: Capability,
        level: int,
        reason: str,
        user_summary: str = "",
        recovery_hint: str = "",
    ) -> None:
        level = max(1, min(3, level))
        old = self._state[capability]
        if old == level:
            return
        self._state[capability] = level
        self._pending_changes.append(
            CapabilityChange(
                capability=capability.value,
                old_level=old,
                new_level=level,
                reason=reason,
                user_summary=user_summary,
                recovery_hint=recovery_hint,
            )
        )
        if self._event_log:
            event = "capability_upgrade" if level > old else "capability_downgrade"
            self._event_log.record(
                event,
                from_phase=old,
                to_phase=level,
                details=f"{capability.value}: {reason}",
            )
        if not self._batch_posture:
            self._update_posture()
        logger.info(
            "Capability %s: L%d → L%d (%s)", capability.value, old, level, reason
        )
        if self._event_bus:
            self._event_bus.emit(
                "capability.changed",
                {
                    "capability": capability.value,
                    "old_level": old,
                    "new_level": level,
                    "reason": reason,
                    "user_summary": user_summary,
                    "recovery_hint": recovery_hint,
                },
                source="capability_registry",
            )

    def diff(self) -> List[CapabilityChange]:
        changes = list(self._pending_changes)
        self._pending_changes.clear()
        return changes

    def snapshot(self) -> dict:
        caps = {}
        changes = {c.capability: c for c in self._pending_changes}
        for cap in Capability:
            entry: dict = {"level": self._state[cap], "changed": cap.value in changes}
            if cap.value in changes:
                c = changes[cap.value]
                entry["change"] = {
                    "from": c.old_level,
                    "to": c.new_level,
                    "summary": c.user_summary,
                    "recovery": c.recovery_hint,
                }
            caps[cap.value] = entry
        return {
            "capabilities": caps,
            "posture": self._posture.value,
        }

    def accept_current_as_baseline(self) -> None:
        """Snapshot current state as the baseline for degradation detection."""
        self._previous = dict(self._state)

    def mark_healthy_probe(self) -> None:
        """Record a probe where no degradation was found.
        After RECOVERY_PROBES_REQUIRED consecutive healthy probes while
        RECOVERING, transitions to NOMINAL.
        """
        if self._posture == Posture.RECOVERING:
            self._consecutive_healthy += 1
            if self._consecutive_healthy >= self.RECOVERY_PROBES_REQUIRED:
                self._posture = Posture.NOMINAL
                self._consecutive_healthy = 0
                logger.info("Posture: RECOVERING → NOMINAL after %d healthy probes",
                            self.RECOVERY_PROBES_REQUIRED)

    def save(self, path: "Path") -> None:
        """Persist current state to JSON file."""
        from pathlib import Path as _Path

        data = {
            "capabilities": {cap.value: self._state[cap] for cap in Capability},
            "posture": self._posture.value,
        }
        p = _Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(data, indent=2))

    def load(self, path: "Path") -> None:
        """Load state from JSON file. Emits diffs for any changes from current."""
        from pathlib import Path as _Path

        p = _Path(path)
        if not p.is_file():
            return
        try:
            data = json.loads(p.read_text())
        except (json.JSONDecodeError, OSError):
            logger.warning("Failed to load capability state from %s", path)
            return
        caps = data.get("capabilities", {})
        for cap in Capability:
            level = caps.get(cap.value)
            if level is not None and isinstance(level, int):
                self.set_level(cap, level, reason="restored from saved state")
        posture_str = data.get("posture")
        if posture_str:
            try:
                self._posture = Posture(posture_str)
            except ValueError:
                pass

    def apply_probe(self, probe_result: "ProbeResult") -> List[CapabilityChange]:
        """Map EcosystemProbe results to per-capability levels.

        Probe->Capability mapping:
        - LOCAL_LLM -> LLM_BACKEND L2, CROSS_EXAM L2
        - REDIS -> EVIDENCE_STORE L2, STATE_BACKEND L2, HEALTH_MONITORING L2
        - CONTEXTDNA -> PROJECT_MEMORY L2, EVIDENCE_STORE L2+
        - IDE_EVENT_BUS -> EVENT_BUS L3, SKILL_SUGGESTIONS L3, HEALTH_MONITORING L3

        Full stack (all 4) -> everything L3.
        """
        from three_surgeons.core.upgrade import InfraCapability

        caps = set(probe_result.capabilities)
        has_llm = InfraCapability.LOCAL_LLM in caps
        has_redis = InfraCapability.REDIS in caps
        has_cdna = InfraCapability.CONTEXTDNA in caps
        has_bus = InfraCapability.IDE_EVENT_BUS in caps
        full_stack = has_llm and has_redis and has_cdna and has_bus

        self._batch_posture = True

        # Evidence Store
        if full_stack:
            self.set_level(Capability.EVIDENCE_STORE, 3,
                           reason="PostgreSQL + bidirectional sync",
                           user_summary="Evidence stored in PostgreSQL with bidirectional sync to SQLite",
                           recovery_hint="")
        elif has_redis or has_cdna:
            self.set_level(Capability.EVIDENCE_STORE, 2,
                           reason="Redis-backed persistence",
                           user_summary="Evidence persists across sessions via Redis",
                           recovery_hint="")
        else:
            self.set_level(Capability.EVIDENCE_STORE, 1,
                           reason="SQLite local store",
                           user_summary="Evidence stored locally in SQLite",
                           recovery_hint="Start Redis: docker compose up -d redis")

        # Cross-Exam
        if full_stack:
            self.set_level(Capability.CROSS_EXAM, 3,
                           reason="3-surgeon team available",
                           user_summary="Full 3-surgeon cross-examination: Atlas + Neurologist + Cardiologist",
                           recovery_hint="")
        elif has_llm:
            self.set_level(Capability.CROSS_EXAM, 2,
                           reason="Local LLM available",
                           user_summary="2-surgeon cross-examination: Atlas + Neurologist",
                           recovery_hint="")
        else:
            self.set_level(Capability.CROSS_EXAM, 1,
                           reason="Atlas only",
                           user_summary="Single-surgeon analysis (Atlas)",
                           recovery_hint="Install local LLM for 2-surgeon cross-exam")

        # State Backend
        if full_stack:
            self.set_level(Capability.STATE_BACKEND, 3,
                           reason="Redis + PostgreSQL with Celery",
                           user_summary="Full shared state: Redis coordination + PostgreSQL warehouse",
                           recovery_hint="")
        elif has_redis:
            self.set_level(Capability.STATE_BACKEND, 2,
                           reason="Redis shared state",
                           user_summary="Shared state via Redis — cross-process coordination enabled",
                           recovery_hint="")
        else:
            self.set_level(Capability.STATE_BACKEND, 1,
                           reason="In-memory with SQLite fallback",
                           user_summary="Local state only — no cross-process sharing",
                           recovery_hint="Start Redis: docker compose up -d redis")

        # Skill Suggestions
        if has_bus:
            self.set_level(Capability.SKILL_SUGGESTIONS, 3,
                           reason="IDE event bus + project memory",
                           user_summary="Real-time skill suggestions via IDE event bus and project memory",
                           recovery_hint="")
        elif has_llm:
            self.set_level(Capability.SKILL_SUGGESTIONS, 2,
                           reason="Local LLM classification",
                           user_summary="Context-weighted skill suggestions via local LLM",
                           recovery_hint="")
        else:
            self.set_level(Capability.SKILL_SUGGESTIONS, 1,
                           reason="Static matching",
                           user_summary="Skill suggestions based on static manifest matching",
                           recovery_hint="Install local LLM for smarter suggestions")

        # Project Memory
        if full_stack:
            self.set_level(Capability.PROJECT_MEMORY, 3,
                           reason="Full ContextDNA heavy mode",
                           user_summary="Full project memory: PostgreSQL warehouse, bidirectional sync, conflict resolution",
                           recovery_hint="")
        elif has_cdna or has_redis:
            self.set_level(Capability.PROJECT_MEMORY, 2,
                           reason="File-persisted across sessions",
                           user_summary="Project memory persists across sessions",
                           recovery_hint="")
        else:
            self.set_level(Capability.PROJECT_MEMORY, 1,
                           reason="Session-scoped",
                           user_summary="Project memory is session-scoped — lost on restart",
                           recovery_hint="Enable ContextDNA for persistent project memory")

        # Health Monitoring
        if has_bus:
            self.set_level(Capability.HEALTH_MONITORING, 3,
                           reason="Live WebSocket health stream",
                           user_summary="Live health monitoring via WebSocket with Cardiologist EKG",
                           recovery_hint="")
        elif has_redis:
            self.set_level(Capability.HEALTH_MONITORING, 2,
                           reason="Automated sentinel probes",
                           user_summary="Automated health monitoring with sentinel and scheduled probes",
                           recovery_hint="")
        else:
            self.set_level(Capability.HEALTH_MONITORING, 1,
                           reason="CLI gains-gate only",
                           user_summary="Manual health checks via gains-gate CLI",
                           recovery_hint="Start Redis for automated monitoring")

        # LLM Backend
        if full_stack:
            self.set_level(Capability.LLM_BACKEND, 3,
                           reason="Hybrid routing with priority queue",
                           user_summary="Hybrid LLM routing: local + external with priority queue and GPU lock",
                           recovery_hint="")
        elif has_llm:
            self.set_level(Capability.LLM_BACKEND, 2,
                           reason="Local LLM with API fallback",
                           user_summary="Local LLM handles classification/extraction, API fallback available",
                           recovery_hint="")
        else:
            self.set_level(Capability.LLM_BACKEND, 1,
                           reason="External API only",
                           user_summary="LLM via external API (your configured provider)",
                           recovery_hint="Install local LLM (MLX/Ollama/LM Studio) for faster local processing")

        # Event Bus
        if has_bus:
            self.set_level(Capability.EVENT_BUS, 3,
                           reason="WebSocket bidirectional",
                           user_summary="Real-time bidirectional events via WebSocket — IDE file/selection events",
                           recovery_hint="")
        else:
            self.set_level(Capability.EVENT_BUS, 1,
                           reason="No event bus",
                           user_summary="No real-time events — poll-based updates only",
                           recovery_hint="Start event bus: 3s serve --event-bus")

        self._batch_posture = False
        self._update_posture()

        return self.diff()

    def _update_posture(self) -> None:
        """Recalculate posture after a level change."""
        old_posture = self._posture
        any_below_baseline = any(
            self._state[c] < self._previous.get(c, 1) for c in Capability
        )
        if any_below_baseline:
            self._posture = Posture.DEGRADED
            self._consecutive_healthy = 0
        elif self._posture == Posture.DEGRADED:
            # Was degraded, no longer below baseline → recovering
            self._posture = Posture.RECOVERING
            self._consecutive_healthy = 0
        if self._posture != old_posture and self._event_bus:
            self._event_bus.emit(
                "posture.changed",
                {"posture": self._posture.value, "previous": old_posture.value},
                source="capability_registry",
            )
