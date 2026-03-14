"""Tests for CapabilityRegistry — per-capability level tracking."""
import json

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


class TestPostureStateMachine:
    def test_starts_nominal(self):
        reg = CapabilityRegistry()
        assert reg.posture == Posture.NOMINAL

    def test_downgrade_triggers_degraded(self):
        reg = CapabilityRegistry()
        reg.set_level(Capability.EVIDENCE_STORE, 2, reason="setup")
        reg.accept_current_as_baseline()
        reg.set_level(Capability.EVIDENCE_STORE, 1, reason="Redis died")
        assert reg.posture == Posture.DEGRADED

    def test_recovery_after_3_healthy_probes(self):
        reg = CapabilityRegistry()
        reg.set_level(Capability.STATE_BACKEND, 2, reason="setup")
        reg.accept_current_as_baseline()
        reg.set_level(Capability.STATE_BACKEND, 1, reason="Redis died")
        assert reg.posture == Posture.DEGRADED
        # Restore level
        reg.set_level(Capability.STATE_BACKEND, 2, reason="Redis back")
        assert reg.posture == Posture.RECOVERING
        # 3 consecutive healthy probes
        reg.mark_healthy_probe()
        assert reg.posture == Posture.RECOVERING
        reg.mark_healthy_probe()
        assert reg.posture == Posture.RECOVERING
        reg.mark_healthy_probe()
        assert reg.posture == Posture.NOMINAL

    def test_degraded_during_recovery_resets_counter(self):
        reg = CapabilityRegistry()
        reg.set_level(Capability.EVENT_BUS, 3, reason="setup")
        reg.accept_current_as_baseline()
        reg.set_level(Capability.EVENT_BUS, 1, reason="WS died")
        reg.set_level(Capability.EVENT_BUS, 3, reason="WS back")
        assert reg.posture == Posture.RECOVERING
        reg.mark_healthy_probe()
        reg.mark_healthy_probe()
        # Another degradation during recovery
        reg.set_level(Capability.EVENT_BUS, 1, reason="WS died again")
        assert reg.posture == Posture.DEGRADED
        # Counter should have reset — need 3 fresh probes
        reg.set_level(Capability.EVENT_BUS, 3, reason="WS back again")
        reg.mark_healthy_probe()
        assert reg.posture == Posture.RECOVERING


class TestPersistence:
    def test_save_creates_file(self, tmp_path):
        reg = CapabilityRegistry()
        reg.set_level(Capability.EVIDENCE_STORE, 2, reason="Redis up")
        path = tmp_path / ".capability_state.json"
        reg.save(path)
        assert path.is_file()

    def test_save_load_roundtrip(self, tmp_path):
        reg = CapabilityRegistry()
        reg.set_level(Capability.LLM_BACKEND, 3, reason="Hybrid routing")
        reg.set_level(Capability.EVENT_BUS, 3, reason="WebSocket connected")
        path = tmp_path / ".capability_state.json"
        reg.save(path)

        reg2 = CapabilityRegistry()
        reg2.load(path)
        assert reg2.get_level(Capability.LLM_BACKEND) == 3
        assert reg2.get_level(Capability.EVENT_BUS) == 3
        assert reg2.get_level(Capability.EVIDENCE_STORE) == 1  # unchanged

    def test_load_missing_file_stays_l1(self, tmp_path):
        reg = CapabilityRegistry()
        reg.load(tmp_path / "nonexistent.json")
        for cap in Capability:
            assert reg.get_level(cap) == 1

    def test_load_corrupt_file_stays_l1(self, tmp_path):
        path = tmp_path / ".capability_state.json"
        path.write_text("not valid json{{{")
        reg = CapabilityRegistry()
        reg.load(path)
        for cap in Capability:
            assert reg.get_level(cap) == 1

    def test_load_emits_diffs_from_default(self, tmp_path):
        """Loading state that differs from L1 default should emit changes."""
        path = tmp_path / ".capability_state.json"
        path.write_text(json.dumps({
            "capabilities": {"evidence_store": 2, "llm_backend": 3},
            "posture": "nominal",
        }))
        reg = CapabilityRegistry()
        reg.load(path)
        changes = reg.diff()
        assert len(changes) == 2
        caps_changed = {c.capability for c in changes}
        assert caps_changed == {"evidence_store", "llm_backend"}
