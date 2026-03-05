"""Tests for the A/B testing engine."""
from __future__ import annotations

import time

import pytest

from three_surgeons.core.ab_testing import (
    ABTestEngine,
    AutonomousTest,
    FORBIDDEN_PARAMS,
    TestStatus,
)
from three_surgeons.core.config import Config
from three_surgeons.core.evidence import EvidenceStore
from three_surgeons.core.state import MemoryBackend


class TestABTestEngine:
    @pytest.fixture
    def engine(self, tmp_path):
        state = MemoryBackend()
        evidence = EvidenceStore(str(tmp_path / "evidence.db"))
        config = Config()
        return ABTestEngine(evidence=evidence, state=state, config=config)

    def test_propose_creates_test(self, engine):
        test = engine.propose(
            param="temperature",
            variant_a="0.7",
            variant_b="0.5",
            hypothesis="Lower temperature improves consistency",
        )
        assert isinstance(test, AutonomousTest)
        assert test.status == TestStatus.PROPOSED
        assert test.param == "temperature"

    def test_forbidden_param_rejected(self, engine):
        with pytest.raises(ValueError, match="forbidden"):
            engine.propose(
                param="safety_gate",
                variant_a="enabled",
                variant_b="disabled",
                hypothesis="Test safety",
            )

    def test_lifecycle_propose_to_conclude(self, engine):
        test = engine.propose("temp", "0.7", "0.5", "hypothesis")
        engine.start_grace_period(test.id)
        engine.activate(test.id)
        engine.measure(test.id, metric_a=0.85, metric_b=0.92)
        result = engine.conclude(test.id, verdict="variant_b wins")
        assert result.status == TestStatus.CONCLUDED
        assert result.verdict == "variant_b wins"

    def test_veto_during_grace(self, engine):
        test = engine.propose("temp", "0.7", "0.5", "hypothesis")
        engine.start_grace_period(test.id)
        result = engine.veto(test.id, reason="Too risky")
        assert result.status == TestStatus.VETOED

    def test_safety_check_cost_limit(self, engine):
        test = engine.propose("temp", "0.7", "0.5", "hypothesis")
        engine.start_grace_period(test.id)
        engine.activate(test.id)
        # Simulate exceeding cost
        t = engine.get_test(test.id)
        t.cost_usd = 3.0
        engine._save_test(t)
        safety = engine.check_safety(test.id)
        assert safety["safe"] is False

    def test_get_active_tests(self, engine):
        t1 = engine.propose("temp", "0.7", "0.5", "h1")
        t2 = engine.propose("tokens", "100", "200", "h2")
        engine.start_grace_period(t1.id)
        engine.activate(t1.id)
        active = engine.get_active_tests()
        assert len(active) >= 1

    def test_security_param_forbidden(self, engine):
        with pytest.raises(ValueError, match="forbidden"):
            engine.propose("security_level", "high", "low", "test")


class TestTestStatusEnum:
    """Verify all required status values exist."""

    def test_all_statuses_defined(self):
        assert TestStatus.PROPOSED.value == "proposed"
        assert TestStatus.GRACE_PERIOD.value == "grace_period"
        assert TestStatus.ACTIVE.value == "active"
        assert TestStatus.MONITORING.value == "monitoring"
        assert TestStatus.CONCLUDED.value == "concluded"
        assert TestStatus.VETOED.value == "vetoed"
        assert TestStatus.REVERTED.value == "reverted"


class TestForbiddenParams:
    """Verify forbidden params list covers required entries."""

    def test_explicit_forbidden_params(self):
        for p in ["safety_gate", "corrigibility", "evidence_retention", "cost_limit", "rate_limit"]:
            assert p in FORBIDDEN_PARAMS, f"{p} should be forbidden"

    def test_security_substring_forbidden(self, tmp_path):
        """Any param containing 'security' or 'auth' should be rejected."""
        state = MemoryBackend()
        evidence = EvidenceStore(str(tmp_path / "evidence.db"))
        engine = ABTestEngine(evidence=evidence, state=state, config=Config())
        with pytest.raises(ValueError, match="forbidden"):
            engine.propose("auth_timeout", "30", "60", "test auth")

    def test_auth_substring_forbidden(self, tmp_path):
        state = MemoryBackend()
        evidence = EvidenceStore(str(tmp_path / "evidence.db"))
        engine = ABTestEngine(evidence=evidence, state=state, config=Config())
        with pytest.raises(ValueError, match="forbidden"):
            engine.propose("my_security_config", "on", "off", "test security")


class TestAutonomousTestDataclass:
    """Verify AutonomousTest fields and defaults."""

    def test_default_values(self):
        t = AutonomousTest(
            id="test-123",
            param="temperature",
            variant_a="0.7",
            variant_b="0.5",
            hypothesis="Lower is better",
            status=TestStatus.PROPOSED,
            created_at=time.time(),
        )
        assert t.activated_at is None
        assert t.concluded_at is None
        assert t.verdict is None
        assert t.cost_usd == 0.0
        assert t.max_duration_hours == 48.0
        assert t.max_cost_usd == 2.0


class TestGracePeriod:
    """Grace period state transitions."""

    @pytest.fixture
    def engine(self, tmp_path):
        state = MemoryBackend()
        evidence = EvidenceStore(str(tmp_path / "evidence.db"))
        return ABTestEngine(evidence=evidence, state=state, config=Config())

    def test_grace_period_sets_status(self, engine):
        test = engine.propose("temp", "0.7", "0.5", "hypothesis")
        result = engine.start_grace_period(test.id)
        assert result.status == TestStatus.GRACE_PERIOD

    def test_cannot_activate_from_proposed(self, engine):
        """Must go through grace period before activation."""
        test = engine.propose("temp", "0.7", "0.5", "hypothesis")
        with pytest.raises(ValueError, match="grace_period"):
            engine.activate(test.id)


class TestMeasurement:
    """Measurement recording."""

    @pytest.fixture
    def engine(self, tmp_path):
        state = MemoryBackend()
        evidence = EvidenceStore(str(tmp_path / "evidence.db"))
        return ABTestEngine(evidence=evidence, state=state, config=Config())

    def test_measure_returns_comparison(self, engine):
        test = engine.propose("temp", "0.7", "0.5", "hypothesis")
        engine.start_grace_period(test.id)
        engine.activate(test.id)
        result = engine.measure(test.id, metric_a=0.85, metric_b=0.92)
        assert "metric_a" in result
        assert "metric_b" in result
        assert "delta" in result
        assert abs(result["delta"] - 0.07) < 0.001

    def test_measure_only_active_test(self, engine):
        """Cannot measure a PROPOSED test."""
        test = engine.propose("temp", "0.7", "0.5", "hypothesis")
        with pytest.raises(ValueError, match="active"):
            engine.measure(test.id, metric_a=0.5, metric_b=0.6)


class TestSafetyChecks:
    """Safety constraint enforcement."""

    @pytest.fixture
    def engine(self, tmp_path):
        state = MemoryBackend()
        evidence = EvidenceStore(str(tmp_path / "evidence.db"))
        return ABTestEngine(evidence=evidence, state=state, config=Config())

    def test_safety_check_passes_under_limits(self, engine):
        test = engine.propose("temp", "0.7", "0.5", "hypothesis")
        engine.start_grace_period(test.id)
        engine.activate(test.id)
        safety = engine.check_safety(test.id)
        assert safety["safe"] is True

    def test_safety_check_duration_exceeded(self, engine):
        test = engine.propose("temp", "0.7", "0.5", "hypothesis")
        engine.start_grace_period(test.id)
        engine.activate(test.id)
        # Simulate activated 49 hours ago (exceeds 48h default)
        t = engine.get_test(test.id)
        t.activated_at = time.time() - (49 * 3600)
        engine._save_test(t)
        safety = engine.check_safety(test.id)
        assert safety["safe"] is False
        assert "duration" in safety["reason"]

    def test_safety_auto_revert_marks_status(self, engine):
        test = engine.propose("temp", "0.7", "0.5", "hypothesis")
        engine.start_grace_period(test.id)
        engine.activate(test.id)
        # Exceed cost
        t = engine.get_test(test.id)
        t.cost_usd = 5.0
        engine._save_test(t)
        safety = engine.check_safety(test.id)
        assert safety["safe"] is False
        # After failed safety check, test should be marked REVERTED
        updated = engine.get_test(test.id)
        assert updated.status == TestStatus.REVERTED


class TestConcludeRecordsEvidence:
    """Conclude should record result in evidence store."""

    @pytest.fixture
    def engine(self, tmp_path):
        state = MemoryBackend()
        evidence = EvidenceStore(str(tmp_path / "evidence.db"))
        return ABTestEngine(evidence=evidence, state=state, config=Config())

    def test_conclude_writes_to_evidence(self, engine):
        test = engine.propose("temp", "0.7", "0.5", "hypothesis")
        engine.start_grace_period(test.id)
        engine.activate(test.id)
        engine.conclude(test.id, verdict="variant_b wins")
        # The evidence store should have the A/B result
        snapshot = engine._evidence.get_evidence_snapshot("temp")
        assert len(snapshot["ab_results"]) >= 1


class TestGetTest:
    """Test retrieval."""

    @pytest.fixture
    def engine(self, tmp_path):
        state = MemoryBackend()
        evidence = EvidenceStore(str(tmp_path / "evidence.db"))
        return ABTestEngine(evidence=evidence, state=state, config=Config())

    def test_get_existing_test(self, engine):
        test = engine.propose("temp", "0.7", "0.5", "hypothesis")
        retrieved = engine.get_test(test.id)
        assert retrieved is not None
        assert retrieved.id == test.id

    def test_get_nonexistent_returns_none(self, engine):
        assert engine.get_test("nonexistent-id") is None


class TestGetActiveTests:
    """Active test listing."""

    @pytest.fixture
    def engine(self, tmp_path):
        state = MemoryBackend()
        evidence = EvidenceStore(str(tmp_path / "evidence.db"))
        return ABTestEngine(evidence=evidence, state=state, config=Config())

    def test_active_excludes_concluded(self, engine):
        t1 = engine.propose("temp", "0.7", "0.5", "h1")
        t2 = engine.propose("tokens", "100", "200", "h2")
        engine.start_grace_period(t1.id)
        engine.activate(t1.id)
        engine.conclude(t1.id, verdict="done")
        engine.start_grace_period(t2.id)
        engine.activate(t2.id)
        active = engine.get_active_tests()
        assert len(active) == 1
        assert active[0].id == t2.id

    def test_active_includes_proposed_and_grace(self, engine):
        """get_active_tests returns all non-terminal tests."""
        t1 = engine.propose("temp", "0.7", "0.5", "h1")
        t2 = engine.propose("tokens", "100", "200", "h2")
        engine.start_grace_period(t2.id)
        active = engine.get_active_tests()
        assert len(active) == 2
