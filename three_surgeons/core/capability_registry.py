"""Capability Registry — per-capability level tracking with Posture state machine.

Tracks 8 capabilities at L1/L2/L3 independently. Emits CapabilityChange
events on transitions. Implements Phase 9 C6 Posture state machine.

Design: docs/plans/2026-03-13-capability-registry-design.md
"""
from __future__ import annotations

import enum
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

    def __init__(self) -> None:
        self._state: Dict[Capability, int] = {cap: 1 for cap in Capability}
        self._previous: Dict[Capability, int] = {cap: 1 for cap in Capability}
        self._pending_changes: List[CapabilityChange] = []
        self._posture = Posture.NOMINAL
        self._consecutive_healthy = 0

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
        self._update_posture()
        logger.info(
            "Capability %s: L%d → L%d (%s)", capability.value, old, level, reason
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

    def _update_posture(self) -> None:
        """Recalculate posture after a level change."""
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
