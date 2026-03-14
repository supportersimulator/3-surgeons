"""Capability Registry — per-capability level tracking with Posture state machine.

Tracks 8 capabilities at L1/L2/L3 independently. Emits CapabilityChange
events on transitions. Implements Phase 9 C6 Posture state machine.

Design: docs/plans/2026-03-13-capability-registry-design.md
"""
from __future__ import annotations

import enum
from dataclasses import dataclass


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
