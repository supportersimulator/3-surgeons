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
