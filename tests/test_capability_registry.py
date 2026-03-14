"""Tests for CapabilityRegistry — per-capability level tracking."""
import pytest
from three_surgeons.core.capability_registry import (
    Capability,
    CapabilityChange,
    Posture,
)


class TestDataStructures:
    def test_capability_enum_has_8_members(self):
        assert len(Capability) == 8

    def test_capability_names(self):
        names = {c.value for c in Capability}
        assert names == {
            "evidence_store",
            "cross_exam",
            "state_backend",
            "skill_suggestions",
            "project_memory",
            "health_monitoring",
            "llm_backend",
            "event_bus",
        }

    def test_posture_enum(self):
        assert Posture.NOMINAL.value == "nominal"
        assert Posture.DEGRADED.value == "degraded"
        assert Posture.RECOVERING.value == "recovering"
        assert Posture.RESTORED.value == "restored"
        assert Posture.SAFE_MODE.value == "safe_mode"

    def test_capability_change_fields(self):
        change = CapabilityChange(
            capability="evidence_store",
            old_level=1,
            new_level=2,
            reason="Redis available",
            user_summary="Evidence now persists across sessions via Redis",
            recovery_hint="",
        )
        assert change.capability == "evidence_store"
        assert change.old_level == 1
        assert change.new_level == 2

    def test_capability_change_is_upgrade(self):
        change = CapabilityChange(
            capability="evidence_store",
            old_level=1,
            new_level=2,
            reason="Redis available",
            user_summary="",
            recovery_hint="",
        )
        assert change.is_upgrade is True

    def test_capability_change_is_downgrade(self):
        change = CapabilityChange(
            capability="llm_backend",
            old_level=3,
            new_level=1,
            reason="Docker stopped",
            user_summary="",
            recovery_hint="Run: docker compose up -d",
        )
        assert change.is_upgrade is False
