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


from three_surgeons.core.capability_registry import CapabilityRegistry


class TestCapabilityRegistryState:
    def test_initial_state_all_l1(self):
        reg = CapabilityRegistry()
        for cap in Capability:
            assert reg.get_level(cap) == 1

    def test_set_level(self):
        reg = CapabilityRegistry()
        reg.set_level(Capability.EVIDENCE_STORE, 2, reason="Redis available")
        assert reg.get_level(Capability.EVIDENCE_STORE) == 2

    def test_set_level_clamps_1_to_3(self):
        reg = CapabilityRegistry()
        reg.set_level(Capability.EVIDENCE_STORE, 5, reason="test")
        assert reg.get_level(Capability.EVIDENCE_STORE) == 3
        reg.set_level(Capability.EVIDENCE_STORE, 0, reason="test")
        assert reg.get_level(Capability.EVIDENCE_STORE) == 1

    def test_diff_empty_when_no_changes(self):
        reg = CapabilityRegistry()
        assert reg.diff() == []

    def test_diff_captures_change(self):
        reg = CapabilityRegistry()
        reg.set_level(
            Capability.LLM_BACKEND,
            2,
            reason="Local LLM detected",
            user_summary="Local LLM now handles classification and extraction",
            recovery_hint="",
        )
        changes = reg.diff()
        assert len(changes) == 1
        assert changes[0].capability == "llm_backend"
        assert changes[0].old_level == 1
        assert changes[0].new_level == 2

    def test_diff_clears_after_read(self):
        reg = CapabilityRegistry()
        reg.set_level(Capability.EVENT_BUS, 3, reason="WebSocket connected")
        _ = reg.diff()
        assert reg.diff() == []

    def test_snapshot_returns_all_levels(self):
        reg = CapabilityRegistry()
        reg.set_level(Capability.EVIDENCE_STORE, 2, reason="test")
        snap = reg.snapshot()
        assert snap["capabilities"]["evidence_store"]["level"] == 2
        assert snap["capabilities"]["llm_backend"]["level"] == 1
        assert "posture" in snap
