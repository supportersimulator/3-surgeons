"""Tests for quality gates: GainsGate, CardioGate, CorrigibilityGate.

TDD: These tests are written first, before the implementation.
Three gate types verify system health before proceeding with operations.
Extracted from gains-gate.sh (229 lines), cardio-gate.sh (147 lines),
corrigibility-gate.sh -- Python rewrite with configurable checks.
"""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from three_surgeons.core.gates import (
    CardioGate,
    CheckResult,
    CorrigibilityGate,
    GainsGate,
    GateResult,
)
from three_surgeons.core.config import Config
from three_surgeons.core.evidence import EvidenceStore
from three_surgeons.core.state import MemoryBackend


# ── CheckResult / GateResult dataclasses ──────────────────────────────


class TestCheckResult:
    def test_fields(self):
        cr = CheckResult(name="test", passed=True, message="ok", critical=False)
        assert cr.name == "test"
        assert cr.passed is True
        assert cr.message == "ok"
        assert cr.critical is False

    def test_critical_default_false(self):
        cr = CheckResult(name="x", passed=True, message="")
        assert cr.critical is False


class TestGateResult:
    def test_fields(self):
        gr = GateResult(
            passed=True,
            checks=[CheckResult(name="a", passed=True, message="ok")],
            summary="All passed",
            duration_ms=42.5,
        )
        assert gr.passed is True
        assert len(gr.checks) == 1
        assert gr.summary == "All passed"
        assert gr.duration_ms == 42.5

    def test_critical_failure_means_gate_failed(self):
        result = GateResult(
            passed=False,
            checks=[CheckResult(name="test", passed=False, message="broken", critical=True)],
            summary="Failed",
            duration_ms=0,
        )
        assert result.passed is False


# ── GainsGate ─────────────────────────────────────────────────────────


class TestGainsGate:
    @pytest.fixture
    def gate(self, tmp_path):
        state = MemoryBackend()
        evidence = EvidenceStore(str(tmp_path / "evidence.db"))
        config = Config()
        return GainsGate(state=state, evidence=evidence, config=config)

    def test_all_checks_pass_when_healthy(self, gate):
        result = gate.run()
        assert isinstance(result, GateResult)
        # evidence and state checks should pass (they're real objects)
        state_check = next((c for c in result.checks if c.name == "state_backend"), None)
        assert state_check is not None
        assert state_check.passed is True

    def test_evidence_store_check_passes(self, gate):
        result = gate.run()
        ev_check = next((c for c in result.checks if c.name == "evidence_store"), None)
        assert ev_check is not None
        assert ev_check.passed is True

    def test_gate_result_has_duration(self, gate):
        result = gate.run()
        assert result.duration_ms >= 0

    def test_gate_has_summary(self, gate):
        result = gate.run()
        assert isinstance(result.summary, str)
        assert len(result.summary) > 0

    def test_critical_failure_fails_gate(self, gate):
        # Manually construct a critical failure result
        result = GateResult(
            passed=False,
            checks=[CheckResult(name="test", passed=False, message="broken", critical=True)],
            summary="Failed",
            duration_ms=0,
        )
        assert result.passed is False

    def test_neurologist_health_check_present(self, gate):
        """Default config includes neurologist_health check."""
        result = gate.run()
        neuro_check = next(
            (c for c in result.checks if c.name == "neurologist_health"), None
        )
        assert neuro_check is not None

    def test_cardiologist_health_check_present(self, gate):
        """Default config includes cardiologist_health check."""
        result = gate.run()
        cardio_check = next(
            (c for c in result.checks if c.name == "cardiologist_health"), None
        )
        assert cardio_check is not None

    def test_non_critical_failure_does_not_fail_gate(self, tmp_path):
        """Non-critical check failure should not cause the gate to fail."""
        state = MemoryBackend()
        evidence = EvidenceStore(str(tmp_path / "evidence.db"))
        # Health checks (neurologist/cardiologist) are non-critical by default
        # because we're in a test environment without live endpoints
        config = Config()
        gate = GainsGate(state=state, evidence=evidence, config=config)
        result = gate.run()
        # Even if health checks fail (no live endpoints), gate passes
        # because only critical checks (evidence_store, state_backend) matter
        critical_failures = [c for c in result.checks if c.critical and not c.passed]
        if not critical_failures:
            assert result.passed is True

    def test_custom_checks_via_config(self, tmp_path):
        """Config can limit which checks are run."""
        state = MemoryBackend()
        evidence = EvidenceStore(str(tmp_path / "evidence.db"))
        config = Config()
        config.gates.gains_gate_checks = ["state_backend"]
        gate = GainsGate(state=state, evidence=evidence, config=config)
        result = gate.run()
        check_names = [c.name for c in result.checks]
        assert "state_backend" in check_names
        # Only the configured check should be present
        assert "neurologist_health" not in check_names


# ── CardioGate ────────────────────────────────────────────────────────


class TestCardioGate:
    def test_rate_limited(self, tmp_path):
        state = MemoryBackend()
        evidence = EvidenceStore(str(tmp_path / "evidence.db"))
        config = Config()
        team = MagicMock()
        gate = CardioGate(state=state, evidence=evidence, surgery_team=team, config=config)
        # Exhaust rate limit (3 reviews per hour)
        for i in range(3):
            state.increment("cardio_gate:reviews_this_hour", ttl=3600)
        result = gate.run()
        rate_check = next((c for c in result.checks if c.name == "rate_limit"), None)
        assert rate_check is not None
        assert rate_check.passed is False

    def test_passes_when_healthy(self, tmp_path):
        state = MemoryBackend()
        evidence = EvidenceStore(str(tmp_path / "evidence.db"))
        config = Config()
        team = MagicMock()
        gate = CardioGate(state=state, evidence=evidence, surgery_team=team, config=config)
        result = gate.run()
        assert isinstance(result, GateResult)

    def test_rate_limit_check_is_critical(self, tmp_path):
        """Rate limit failure should be critical -- blocks the gate."""
        state = MemoryBackend()
        evidence = EvidenceStore(str(tmp_path / "evidence.db"))
        config = Config()
        team = MagicMock()
        gate = CardioGate(state=state, evidence=evidence, surgery_team=team, config=config)
        # Exhaust rate limit
        for i in range(3):
            state.increment("cardio_gate:reviews_this_hour", ttl=3600)
        result = gate.run()
        rate_check = next((c for c in result.checks if c.name == "rate_limit"), None)
        assert rate_check.critical is True
        assert result.passed is False

    def test_includes_gains_gate_checks(self, tmp_path):
        """CardioGate chains: runs gains gate checks first."""
        state = MemoryBackend()
        evidence = EvidenceStore(str(tmp_path / "evidence.db"))
        config = Config()
        team = MagicMock()
        gate = CardioGate(state=state, evidence=evidence, surgery_team=team, config=config)
        result = gate.run()
        # Should include gains gate checks (state_backend, evidence_store, etc.)
        check_names = [c.name for c in result.checks]
        assert "rate_limit" in check_names
        assert "state_backend" in check_names or "evidence_store" in check_names

    def test_has_duration(self, tmp_path):
        state = MemoryBackend()
        evidence = EvidenceStore(str(tmp_path / "evidence.db"))
        config = Config()
        team = MagicMock()
        gate = CardioGate(state=state, evidence=evidence, surgery_team=team, config=config)
        result = gate.run()
        assert result.duration_ms >= 0


# ── CorrigibilityGate ─────────────────────────────────────────────────


class TestCorrigibilityGate:
    def test_safe_action_passes(self):
        config = Config()
        gate = CorrigibilityGate(config=config)
        result = gate.run("refactor the authentication module")
        assert result.passed is True

    def test_destructive_action_flagged(self):
        config = Config()
        gate = CorrigibilityGate(config=config)
        result = gate.run("drop all database tables")
        assert result.passed is False

    def test_gate_bypass_flagged(self):
        config = Config()
        gate = CorrigibilityGate(config=config)
        result = gate.run("disable the corrigibility gate")
        assert result.passed is False

    def test_safety_bypass_flagged(self):
        config = Config()
        gate = CorrigibilityGate(config=config)
        result = gate.run("bypass safety constraints to speed up deployment")
        assert result.passed is False

    def test_force_push_flagged(self):
        config = Config()
        gate = CorrigibilityGate(config=config)
        result = gate.run("force push to main branch")
        assert result.passed is False

    def test_returns_gate_result(self):
        config = Config()
        gate = CorrigibilityGate(config=config)
        result = gate.run("read the log files")
        assert isinstance(result, GateResult)
        assert result.duration_ms >= 0
        assert len(result.checks) > 0

    def test_has_reasoning_in_message(self):
        config = Config()
        gate = CorrigibilityGate(config=config)
        result = gate.run("delete all production data without backup")
        assert result.passed is False
        # Should have a message explaining why it was flagged
        failed_check = next((c for c in result.checks if not c.passed), None)
        assert failed_check is not None
        assert len(failed_check.message) > 0

    def test_modify_gate_logic_flagged(self):
        config = Config()
        gate = CorrigibilityGate(config=config)
        result = gate.run("modify the gate logic to skip checks")
        assert result.passed is False

    def test_benign_actions_pass(self):
        config = Config()
        gate = CorrigibilityGate(config=config)
        for action in [
            "run the test suite",
            "read configuration files",
            "analyze code coverage",
            "generate a report",
        ]:
            result = gate.run(action)
            assert result.passed is True, f"Expected pass for: {action}"
