"""Tests for CommandRequirements, CommandResult, and GateResult."""
from __future__ import annotations

import pytest

from three_surgeons.core.requirements import (
    CommandRequirements,
    CommandResult,
    GateResult,
)


def test_gate_result_values():
    assert GateResult.PROCEED.value == "proceed"
    assert GateResult.DEGRADED.value == "degraded"
    assert GateResult.BLOCKED.value == "blocked"


def test_command_requirements_defaults():
    reqs = CommandRequirements()
    assert reqs.min_llms == 0
    assert reqs.needs_state is False
    assert reqs.needs_evidence is False
    assert reqs.needs_git is False
    assert reqs.preconditions == []
    assert reqs.recommended_llms == 0


def test_command_requirements_custom():
    reqs = CommandRequirements(
        min_llms=2, needs_state=True, needs_evidence=True,
        needs_git=True, preconditions=["ab_test_active"],
        recommended_llms=3,
    )
    assert reqs.min_llms == 2
    assert reqs.preconditions == ["ab_test_active"]


def test_command_result_success():
    result = CommandResult(success=True, data={"key": "value"})
    assert result.success is True
    assert result.degraded is False
    assert result.degradation_notes == []
    assert result.blocked is False
    assert result.blocked_reason == ""


def test_command_result_degraded():
    result = CommandResult(
        success=True, data={},
        degraded=True, degradation_notes=["Running with 1 surgeon (3 recommended)"],
    )
    assert result.degraded is True
    assert len(result.degradation_notes) == 1


def test_command_result_blocked():
    result = CommandResult(
        success=False, data={},
        blocked=True, blocked_reason="Requires at least 1 LLM endpoint",
    )
    assert result.blocked is True
    assert "LLM" in result.blocked_reason


def test_command_result_to_dict():
    result = CommandResult(success=True, data={"status": "ok"}, degraded=True,
                           degradation_notes=["note1"])
    d = result.to_dict()
    assert d["success"] is True
    assert d["data"] == {"status": "ok"}
    assert d["degraded"] is True
    assert d["degradation_notes"] == ["note1"]


def test_blocked_result_helper():
    result = CommandResult.blocked_result("No git repo found")
    assert result.success is False
    assert result.blocked is True
    assert result.blocked_reason == "No git repo found"
    assert result.data == {}


from unittest.mock import MagicMock
from three_surgeons.core.requirements import RuntimeContext, check_requirements


def _make_ctx(healthy_llms=0, state=True, evidence=True, git=False, git_root=None, precondition_checker=None):
    """Helper to build RuntimeContext for tests."""
    llms = [MagicMock() for _ in range(healthy_llms)]
    return RuntimeContext(
        healthy_llms=llms,
        state=MagicMock() if state else None,
        evidence=MagicMock() if evidence else None,
        git_available=git,
        git_root=git_root,
        config=MagicMock(),
        precondition_checker=precondition_checker,
    )


class TestCheckRequirements:
    def test_proceed_no_requirements(self):
        ctx = _make_ctx()
        reqs = CommandRequirements()
        gate, notes = check_requirements(reqs, ctx)
        assert gate == GateResult.PROCEED
        assert notes == []

    def test_blocked_insufficient_llms(self):
        ctx = _make_ctx(healthy_llms=0)
        reqs = CommandRequirements(min_llms=1)
        gate, notes = check_requirements(reqs, ctx)
        assert gate == GateResult.BLOCKED
        assert "LLM" in notes[0]

    def test_blocked_needs_state(self):
        ctx = _make_ctx(state=False)
        reqs = CommandRequirements(needs_state=True)
        gate, notes = check_requirements(reqs, ctx)
        assert gate == GateResult.BLOCKED
        assert "state" in notes[0].lower()

    def test_blocked_needs_evidence(self):
        ctx = _make_ctx(evidence=False)
        reqs = CommandRequirements(needs_evidence=True)
        gate, notes = check_requirements(reqs, ctx)
        assert gate == GateResult.BLOCKED
        assert "evidence" in notes[0].lower()

    def test_blocked_needs_git(self):
        ctx = _make_ctx(git=False)
        reqs = CommandRequirements(needs_git=True)
        gate, notes = check_requirements(reqs, ctx)
        assert gate == GateResult.BLOCKED
        assert "git" in notes[0].lower()

    def test_degraded_fewer_than_recommended_llms(self):
        ctx = _make_ctx(healthy_llms=1)
        reqs = CommandRequirements(min_llms=1, recommended_llms=3)
        gate, notes = check_requirements(reqs, ctx)
        assert gate == GateResult.DEGRADED
        assert "1" in notes[0] and "3" in notes[0]

    def test_proceed_meets_recommended(self):
        ctx = _make_ctx(healthy_llms=3)
        reqs = CommandRequirements(min_llms=1, recommended_llms=3)
        gate, notes = check_requirements(reqs, ctx)
        assert gate == GateResult.PROCEED

    def test_blocked_precondition_fails(self):
        checker = MagicMock(return_value=(False, "No active A/B test"))
        ctx = _make_ctx(precondition_checker=checker)
        reqs = CommandRequirements(preconditions=["ab_test_active"])
        gate, notes = check_requirements(reqs, ctx)
        assert gate == GateResult.BLOCKED
        assert "A/B test" in notes[0]
        checker.assert_called_once_with("ab_test_active")

    def test_proceed_precondition_passes(self):
        checker = MagicMock(return_value=(True, ""))
        ctx = _make_ctx(precondition_checker=checker)
        reqs = CommandRequirements(preconditions=["ab_test_active"])
        gate, notes = check_requirements(reqs, ctx)
        assert gate == GateResult.PROCEED

    def test_blocked_takes_priority_over_degraded(self):
        """If both blocked and degraded conditions exist, blocked wins."""
        ctx = _make_ctx(healthy_llms=0)
        reqs = CommandRequirements(min_llms=1, recommended_llms=3)
        gate, notes = check_requirements(reqs, ctx)
        assert gate == GateResult.BLOCKED
