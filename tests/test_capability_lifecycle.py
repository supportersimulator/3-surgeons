"""Full integration lifecycle test for CapabilityRegistry.

Covers: startup → probe → upgrade → degrade → recover → safe_mode →
exit safe mode → recover to nominal → persistence round-trip.
"""
from __future__ import annotations

import pytest

from three_surgeons.core.capability_registry import (
    Capability,
    CapabilityRegistry,
    Posture,
)
from three_surgeons.core.upgrade import InfraCapability, ProbeResult
from three_surgeons.core.capability_messages import (
    format_changes_message,
    format_snapshot_message,
)


class MockEventBus:
    """Captures emitted events for assertion."""

    def __init__(self) -> None:
        self.events: list[tuple[str, dict, str | None]] = []

    def emit(self, event_type: str, data: dict, source: str | None = None) -> None:
        self.events.append((event_type, data, source))


def _probe(*caps: InfraCapability) -> ProbeResult:
    """Helper to build a ProbeResult with given capabilities."""
    return ProbeResult(capabilities=list(caps))


class TestCapabilityLifecycle:

    def test_full_lifecycle(self, tmp_path):
        reg = CapabilityRegistry()

        # --- 1. Startup: all L1, NOMINAL ---
        for cap in Capability:
            assert reg.get_level(cap) == 1
        assert reg.posture == Posture.NOMINAL

        # --- 2. First probe: LLM + Redis ---
        changes = reg.apply_probe(_probe(InfraCapability.LOCAL_LLM, InfraCapability.REDIS))

        assert reg.get_level(Capability.LLM_BACKEND) == 2
        assert reg.get_level(Capability.CROSS_EXAM) == 2
        assert reg.get_level(Capability.SKILL_SUGGESTIONS) == 2
        assert reg.get_level(Capability.EVIDENCE_STORE) == 2
        assert reg.get_level(Capability.STATE_BACKEND) == 2
        assert reg.get_level(Capability.HEALTH_MONITORING) == 2
        assert reg.get_level(Capability.PROJECT_MEMORY) == 2
        # No bus → EVENT_BUS stays L1
        assert reg.get_level(Capability.EVENT_BUS) == 1
        assert reg.posture == Posture.NOMINAL
        assert len(changes) > 0

        # --- 3. Accept baseline ---
        reg.accept_current_as_baseline()

        # --- 4. Full stack probe → all L3 ---
        reg.apply_probe(_probe(
            InfraCapability.LOCAL_LLM,
            InfraCapability.REDIS,
            InfraCapability.CONTEXTDNA,
            InfraCapability.IDE_EVENT_BUS,
        ))

        for cap in Capability:
            assert reg.get_level(cap) == 3, f"{cap.value} should be L3"
        # Upgraded above baseline → still NOMINAL
        assert reg.posture == Posture.NOMINAL

        # --- 5. Accept new baseline at L3 ---
        reg.accept_current_as_baseline()

        # --- 6. Degradation: only REDIS left ---
        reg.apply_probe(_probe(InfraCapability.REDIS))

        # Caps that need LLM/CDNA/bus should drop
        assert reg.get_level(Capability.LLM_BACKEND) == 1
        assert reg.get_level(Capability.CROSS_EXAM) == 1
        assert reg.get_level(Capability.EVENT_BUS) == 1
        assert reg.get_level(Capability.SKILL_SUGGESTIONS) == 1
        # Redis-dependent stay at L2
        assert reg.get_level(Capability.STATE_BACKEND) == 2
        assert reg.get_level(Capability.EVIDENCE_STORE) == 2
        assert reg.get_level(Capability.HEALTH_MONITORING) == 2
        assert reg.posture == Posture.DEGRADED

        # --- 7. Partial recovery: LLM + Redis ---
        reg.apply_probe(_probe(InfraCapability.LOCAL_LLM, InfraCapability.REDIS))

        # Still below L3 baseline for several caps → DEGRADED
        assert reg.get_level(Capability.EVENT_BUS) == 1  # still no bus
        assert reg.posture == Posture.DEGRADED

        # --- 8. Full recovery: all 4 → back to L3 ---
        reg.apply_probe(_probe(
            InfraCapability.LOCAL_LLM,
            InfraCapability.REDIS,
            InfraCapability.CONTEXTDNA,
            InfraCapability.IDE_EVENT_BUS,
        ))

        for cap in Capability:
            assert reg.get_level(cap) == 3, f"{cap.value} should be L3 after full recovery"
        assert reg.posture == Posture.RECOVERING

        # --- 9. Three healthy probes → NOMINAL ---
        for i in range(3):
            reg.mark_healthy_probe()
        assert reg.posture == Posture.NOMINAL

        # --- 10. Safe mode ---
        reg.enter_safe_mode(reason="testing safe mode")
        for cap in Capability:
            assert reg.get_level(cap) == 1, f"{cap.value} should be L1 in safe mode"
        assert reg.posture == Posture.SAFE_MODE

        # --- 11. Exit safe mode → levels restored, RECOVERING ---
        reg.exit_safe_mode(reason="test cleared")
        for cap in Capability:
            assert reg.get_level(cap) == 3, f"{cap.value} should restore to L3"
        assert reg.posture == Posture.RECOVERING

        # --- 12. Recovery to NOMINAL again ---
        for i in range(3):
            reg.mark_healthy_probe()
        assert reg.posture == Posture.NOMINAL

        # --- 13. Persistence round-trip ---
        save_path = tmp_path / "caps.json"
        reg.save(save_path)

        fresh = CapabilityRegistry()
        # Fresh starts at L1
        assert fresh.get_level(Capability.LLM_BACKEND) == 1
        fresh.load(save_path)
        for cap in Capability:
            assert fresh.get_level(cap) == reg.get_level(cap), (
                f"{cap.value} mismatch after load"
            )

    def test_event_bus_integration(self):
        bus = MockEventBus()
        reg = CapabilityRegistry(event_bus=bus)

        # set_level emits capability.changed
        reg.set_level(Capability.LLM_BACKEND, 2, reason="test upgrade")
        cap_events = [e for e in bus.events if e[0] == "capability.changed"]
        assert len(cap_events) == 1
        assert cap_events[0][1]["capability"] == "llm_backend"
        assert cap_events[0][1]["old_level"] == 1
        assert cap_events[0][1]["new_level"] == 2

        bus.events.clear()

        # enter_safe_mode emits posture.changed with posture="safe_mode"
        reg.enter_safe_mode(reason="bus test")
        posture_events = [e for e in bus.events if e[0] == "posture.changed"]
        assert len(posture_events) == 1
        assert posture_events[0][1]["posture"] == "safe_mode"

        bus.events.clear()

        # exit_safe_mode emits posture.changed with posture="recovering"
        reg.exit_safe_mode(reason="bus test clear")
        posture_events = [e for e in bus.events if e[0] == "posture.changed"]
        assert len(posture_events) == 1
        assert posture_events[0][1]["posture"] == "recovering"

    def test_message_formatting_lifecycle(self):
        reg = CapabilityRegistry()

        # Apply full stack probe
        changes = reg.apply_probe(_probe(
            InfraCapability.LOCAL_LLM,
            InfraCapability.REDIS,
            InfraCapability.CONTEXTDNA,
            InfraCapability.IDE_EVENT_BUS,
        ))

        # format_changes_message
        msg = format_changes_message(changes, posture=reg.posture.value)
        assert isinstance(msg, str)
        assert len(msg) > 0
        assert "L3" in msg

        # format_snapshot_message
        snap = reg.snapshot()
        snap_msg = format_snapshot_message(snap)
        assert isinstance(snap_msg, str)
        assert len(snap_msg) > 0
        assert "L3" in snap_msg
