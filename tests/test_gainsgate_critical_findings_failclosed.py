"""Regression contract: configured critical-finding checks must not certify unknown state.

Test-only commit should fail on missing, malformed and unreadable count; the
positive controls must continue to pass. No external services or credentials.
"""
from __future__ import annotations

import logging

import pytest

from three_surgeons.core.config import Config
from three_surgeons.core.evidence import EvidenceStore
from three_surgeons.core.gates import GainsGate
from three_surgeons.core.state import MemoryBackend


@pytest.fixture
def rig(tmp_path):
    state = MemoryBackend()
    config = Config()
    config.gates.gains_gate_checks = ["critical_findings"]
    evidence = EvidenceStore(str(tmp_path / "evidence.db"))
    return state, GainsGate(state=state, evidence=evidence, config=config)


def _critical_result(gate):
    aggregate = gate.run()
    check = next(c for c in aggregate.checks if c.name == "critical_findings")
    assert check.critical is True
    return aggregate, check


def test_zero_unresolved_findings_passes(rig):
    state, gate = rig
    state.set("critical_findings:count", "0")
    result, check = _critical_result(gate)
    assert check.passed is True
    assert result.passed is True


def test_positive_unresolved_findings_blocks(rig):
    state, gate = rig
    state.set("critical_findings:count", "3")
    result, check = _critical_result(gate)
    assert check.passed is False
    assert result.passed is False
    assert "3 unresolved" in check.message


@pytest.mark.parametrize("value", ["NaN", "", "1.5"])
def test_malformed_critical_count_blocks_with_recovery(rig, value, caplog):
    state, gate = rig
    state.set("critical_findings:count", value)
    with caplog.at_level(logging.ERROR, logger="three_surgeons.core.gates"):
        result, check = _critical_result(gate)
    assert check.passed is False
    assert result.passed is False
    assert "critical_findings:count" in check.message
    assert "Recovery:" in check.message
    assert "critical_findings" in caplog.text


def test_absent_critical_count_blocks_instead_of_assuming_zero(rig, caplog):
    _state, gate = rig
    with caplog.at_level(logging.ERROR, logger="three_surgeons.core.gates"):
        result, check = _critical_result(gate)
    assert check.passed is False
    assert result.passed is False
    assert "critical_findings:count" in check.message
    assert "Recovery:" in check.message
    assert "critical_findings" in caplog.text


def test_state_read_error_blocks_and_logs(rig, monkeypatch, caplog):
    state, gate = rig

    def unavailable(_key):
        raise OSError("synthetic state read failure")

    monkeypatch.setattr(state, "get", unavailable)
    with caplog.at_level(logging.ERROR, logger="three_surgeons.core.gates"):
        result, check = _critical_result(gate)
    assert check.passed is False
    assert result.passed is False
    assert "critical_findings:count" in check.message
    assert "Recovery:" in check.message
    assert "synthetic state read failure" in caplog.text
