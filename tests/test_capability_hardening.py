"""Tests for capability registry hardening (V17-V22).

Covers: concurrency safety, event batching, declarative probe mapping,
Redis persistence, probe-after-transition, adapter protocol.
"""
from __future__ import annotations

import threading
from unittest.mock import MagicMock

import pytest

from three_surgeons.core.capability_registry import (
    Capability,
    CapabilityRegistry,
    Posture,
    get_probe_rules,
)


# --- Task 1: Concurrency Safety ---

class TestConcurrencySafety:
    """Per-capability locking prevents races."""

    def test_concurrent_set_level_no_lost_updates(self) -> None:
        """Two threads setting different capabilities don't interfere."""
        reg = CapabilityRegistry()
        barrier = threading.Barrier(2)

        def set_llm():
            barrier.wait()
            reg.set_level(Capability.LLM_BACKEND, 3, reason="thread-1")

        def set_redis():
            barrier.wait()
            reg.set_level(Capability.STATE_BACKEND, 3, reason="thread-2")

        t1 = threading.Thread(target=set_llm)
        t2 = threading.Thread(target=set_redis)
        t1.start()
        t2.start()
        t1.join(timeout=5)
        t2.join(timeout=5)

        assert reg.get_level(Capability.LLM_BACKEND) == 3
        assert reg.get_level(Capability.STATE_BACKEND) == 3

    def test_concurrent_same_capability_serialized(self) -> None:
        """Two threads setting the SAME capability serialize correctly."""
        reg = CapabilityRegistry()
        barrier = threading.Barrier(2)

        def writer(level: int):
            barrier.wait()
            reg.set_level(Capability.LLM_BACKEND, level, reason=f"set-{level}")

        t1 = threading.Thread(target=writer, args=(2,))
        t2 = threading.Thread(target=writer, args=(3,))
        t1.start()
        t2.start()
        t1.join(timeout=5)
        t2.join(timeout=5)

        # Final state must be one of the two — no corruption
        final = reg.get_level(Capability.LLM_BACKEND)
        assert final in (2, 3)

    def test_diff_is_atomic(self) -> None:
        """diff() clears pending changes atomically — no partial reads."""
        reg = CapabilityRegistry()
        reg.set_level(Capability.LLM_BACKEND, 2, reason="a")
        reg.set_level(Capability.STATE_BACKEND, 2, reason="b")
        changes = reg.diff()
        assert len(changes) == 2
        assert reg.diff() == []  # Cleared


# --- Task 2: Event Batching ---

class TestEventBatching:
    """Rapid events collapse into single transition."""

    def test_rapid_changes_batch_into_one_event(self) -> None:
        """Multiple rapid changes to same capability produce one net event."""
        bus = MagicMock()
        reg = CapabilityRegistry(event_bus=bus)

        # Rapid-fire: L1 -> L2 -> L1 -> L3
        with reg.batch_events():
            reg.set_level(Capability.LLM_BACKEND, 2, reason="up")
            reg.set_level(Capability.LLM_BACKEND, 1, reason="down")
            reg.set_level(Capability.LLM_BACKEND, 3, reason="up-again")

        # Only ONE capability.changed event for LLM_BACKEND (net: L1->L3)
        cap_events = [
            c for c in bus.emit.call_args_list
            if c[0][0] == "capability.changed"
            and c[0][1]["capability"] == "llm_backend"
        ]
        assert len(cap_events) == 1
        assert cap_events[0][0][1]["old_level"] == 1
        assert cap_events[0][0][1]["new_level"] == 3

    def test_batch_no_event_if_net_zero(self) -> None:
        """If capability returns to original level within batch, no event."""
        bus = MagicMock()
        reg = CapabilityRegistry(event_bus=bus)

        with reg.batch_events():
            reg.set_level(Capability.LLM_BACKEND, 3, reason="up")
            reg.set_level(Capability.LLM_BACKEND, 1, reason="back-down")

        # Net change is L1->L1 = no event
        cap_events = [
            c for c in bus.emit.call_args_list
            if c[0][0] == "capability.changed"
            and c[0][1]["capability"] == "llm_backend"
        ]
        assert len(cap_events) == 0

    def test_batch_different_capabilities_separate_events(self) -> None:
        """Batching collapses per-capability, not across capabilities."""
        bus = MagicMock()
        reg = CapabilityRegistry(event_bus=bus)

        with reg.batch_events():
            reg.set_level(Capability.LLM_BACKEND, 3, reason="llm-up")
            reg.set_level(Capability.STATE_BACKEND, 2, reason="redis-up")

        cap_events = [
            c for c in bus.emit.call_args_list
            if c[0][0] == "capability.changed"
        ]
        assert len(cap_events) == 2

    def test_outside_batch_events_fire_immediately(self) -> None:
        """Without batch context, events fire on every set_level."""
        bus = MagicMock()
        reg = CapabilityRegistry(event_bus=bus)

        reg.set_level(Capability.LLM_BACKEND, 2, reason="a")
        reg.set_level(Capability.LLM_BACKEND, 3, reason="b")

        cap_events = [
            c for c in bus.emit.call_args_list
            if c[0][0] == "capability.changed"
        ]
        assert len(cap_events) == 2


# --- Task 3: Declarative Probe Mapping ---

class TestDeclarativeProbeMapping:
    """Probe rules are data, not code."""

    def test_probe_rules_cover_all_capabilities(self) -> None:
        """Every Capability enum value has at least one probe rule."""
        rules = get_probe_rules()
        covered = {rule["capability"] for rule in rules}
        for cap in Capability:
            assert cap in covered, f"{cap.value} missing from PROBE_RULES"

    def test_declarative_matches_full_stack(self) -> None:
        """Declarative probe produces correct result for full stack."""
        from three_surgeons.core.upgrade import InfraCapability, ProbeResult

        probe = ProbeResult(
            capabilities=[
                InfraCapability.LOCAL_LLM,
                InfraCapability.REDIS,
                InfraCapability.CONTEXTDNA,
                InfraCapability.IDE_EVENT_BUS,
            ],
            detected_phase=3,
        )
        reg = CapabilityRegistry()
        reg.apply_probe(probe)

        # Full stack = all L3
        for cap in Capability:
            assert reg.get_level(cap) == 3, f"{cap.value} should be L3 with full stack"

    def test_declarative_llm_only(self) -> None:
        """LLM-only scenario sets correct levels."""
        from three_surgeons.core.upgrade import InfraCapability, ProbeResult

        probe = ProbeResult(
            capabilities=[InfraCapability.LOCAL_LLM],
            detected_phase=1,
        )
        reg = CapabilityRegistry()
        reg.apply_probe(probe)

        assert reg.get_level(Capability.LLM_BACKEND) == 2
        assert reg.get_level(Capability.CROSS_EXAM) == 2
        assert reg.get_level(Capability.SKILL_SUGGESTIONS) == 2
        assert reg.get_level(Capability.STATE_BACKEND) == 1
        assert reg.get_level(Capability.EVENT_BUS) == 1

    def test_declarative_redis_only(self) -> None:
        """Redis-only scenario sets correct levels."""
        from three_surgeons.core.upgrade import InfraCapability, ProbeResult

        probe = ProbeResult(
            capabilities=[InfraCapability.REDIS],
            detected_phase=1,
        )
        reg = CapabilityRegistry()
        reg.apply_probe(probe)

        assert reg.get_level(Capability.STATE_BACKEND) == 2
        assert reg.get_level(Capability.EVIDENCE_STORE) == 2
        assert reg.get_level(Capability.HEALTH_MONITORING) == 2
        assert reg.get_level(Capability.PROJECT_MEMORY) == 2
        assert reg.get_level(Capability.LLM_BACKEND) == 1

    def test_declarative_no_infra(self) -> None:
        """No infra = all L1."""
        from three_surgeons.core.upgrade import ProbeResult

        probe = ProbeResult(capabilities=[], detected_phase=1)
        reg = CapabilityRegistry()
        reg.apply_probe(probe)

        for cap in Capability:
            assert reg.get_level(cap) == 1, f"{cap.value} should be L1 with no infra"


# --- Task 4: Redis Persistence ---

class TestRedisPersistence:
    """State survives process restart via Redis."""

    def _make_fake_redis(self):
        store = {}

        class FakeRedis:
            def hset(self, key, mapping):
                store[key] = dict(mapping)

            def hgetall(self, key):
                return store.get(key, {})

            def set(self, key, value):
                store[key] = value

            def get(self, key):
                return store.get(key)

            def delete(self, key):
                store.pop(key, None)

            def ping(self):
                return True

        return FakeRedis(), store

    def test_persist_and_rehydrate_levels(self) -> None:
        """Levels persist to Redis and restore on new registry instance."""
        redis, _ = self._make_fake_redis()
        reg1 = CapabilityRegistry()
        reg1.set_level(Capability.LLM_BACKEND, 3, reason="detected")
        reg1.persist_to_redis(redis)

        reg2 = CapabilityRegistry()
        reg2.rehydrate_from_redis(redis)
        assert reg2.get_level(Capability.LLM_BACKEND) == 3

    def test_rehydrate_empty_redis_stays_l1(self) -> None:
        """If Redis has no state, registry stays at L1 defaults."""
        redis, _ = self._make_fake_redis()
        reg = CapabilityRegistry()
        reg.rehydrate_from_redis(redis)
        for cap in Capability:
            assert reg.get_level(cap) == 1

    def test_rehydrate_redis_down_starts_degraded(self) -> None:
        """If Redis is unreachable during rehydrate, start in DEGRADED."""

        class DeadRedis:
            def hgetall(self, key):
                raise ConnectionError("Redis down")

            def ping(self):
                raise ConnectionError("Redis down")

        reg = CapabilityRegistry()
        reg.rehydrate_from_redis(DeadRedis())
        assert reg.posture == Posture.DEGRADED

    def test_safe_mode_persists_to_redis(self) -> None:
        """Safe mode flag persists so restart doesn't clear it."""
        redis, _ = self._make_fake_redis()
        reg1 = CapabilityRegistry()
        reg1.enter_safe_mode(reason="test")
        reg1.persist_to_redis(redis)

        reg2 = CapabilityRegistry()
        reg2.rehydrate_from_redis(redis)
        assert reg2.posture == Posture.SAFE_MODE


# --- Task 5: Probe-After-Transition ---

class TestProbeAfterTransition:
    """Re-probe after level change to catch transient failures."""

    def test_recheck_callback_called_on_downgrade(self) -> None:
        """When a capability downgrades, recheck_fn is called."""
        recheck_calls = []

        def fake_recheck(capability: str):
            recheck_calls.append(capability)

        reg = CapabilityRegistry(recheck_fn=fake_recheck)
        reg.set_level(Capability.LLM_BACKEND, 2, reason="initial")
        reg.accept_current_as_baseline()
        reg.set_level(Capability.LLM_BACKEND, 1, reason="failure")

        assert "llm_backend" in recheck_calls

    def test_no_recheck_on_upgrade(self) -> None:
        """Upgrades don't trigger recheck — only downgrades do."""
        recheck_calls = []

        def fake_recheck(capability: str):
            recheck_calls.append(capability)

        reg = CapabilityRegistry(recheck_fn=fake_recheck)
        reg.set_level(Capability.LLM_BACKEND, 3, reason="upgrade")

        assert recheck_calls == []

    def test_no_recheck_without_callback(self) -> None:
        """If no recheck_fn provided, transitions work normally."""
        reg = CapabilityRegistry()
        reg.set_level(Capability.LLM_BACKEND, 2, reason="up")
        reg.accept_current_as_baseline()
        reg.set_level(Capability.LLM_BACKEND, 1, reason="down")
        assert reg.get_level(Capability.LLM_BACKEND) == 1

    def test_recheck_exception_does_not_crash(self) -> None:
        """If recheck_fn raises, the transition still completes."""
        def bad_recheck(capability: str):
            raise RuntimeError("recheck exploded")

        reg = CapabilityRegistry(recheck_fn=bad_recheck)
        reg.set_level(Capability.LLM_BACKEND, 2, reason="up")
        reg.accept_current_as_baseline()
        reg.set_level(Capability.LLM_BACKEND, 1, reason="down")
        assert reg.get_level(Capability.LLM_BACKEND) == 1


# --- Task 6: Adapter Protocol ---

class TestAdapterProtocol:
    """Cross-boundary probe protocol."""

    def test_protocol_probe_satisfies_interface(self) -> None:
        """Objects implementing the protocol are accepted."""
        from three_surgeons.core.probe_protocol import CapabilityProbe

        class FakeProbe:
            def name(self) -> str:
                return "test_probe"

            def probe(self) -> bool:
                return True

            def capability(self) -> str:
                return "llm_backend"

        p = FakeProbe()
        assert isinstance(p, CapabilityProbe)
        assert p.probe() is True

    def test_register_and_run_custom_probe(self) -> None:
        """Custom probes can be registered and run via registry."""
        probes_run = []

        class CustomProbe:
            def name(self) -> str:
                return "redis_check"

            def probe(self) -> bool:
                probes_run.append("redis_check")
                return True

            def capability(self) -> str:
                return "state_backend"

        reg = CapabilityRegistry()
        reg.register_probe(CustomProbe())
        results = reg.run_probes()

        assert "redis_check" in probes_run
        assert results["redis_check"] is True

    def test_failed_probe_returns_false(self) -> None:
        """Probe returning False is captured without exception."""

        class FailingProbe:
            def name(self) -> str:
                return "dead_service"

            def probe(self) -> bool:
                return False

            def capability(self) -> str:
                return "llm_backend"

        reg = CapabilityRegistry()
        reg.register_probe(FailingProbe())
        results = reg.run_probes()
        assert results["dead_service"] is False

    def test_probe_exception_treated_as_failure(self) -> None:
        """Probe that raises is treated as failure, not crash."""

        class CrashingProbe:
            def name(self) -> str:
                return "crasher"

            def probe(self) -> bool:
                raise ConnectionError("boom")

            def capability(self) -> str:
                return "redis"

        reg = CapabilityRegistry()
        reg.register_probe(CrashingProbe())
        results = reg.run_probes()
        assert results["crasher"] is False
