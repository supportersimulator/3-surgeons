"""Tests for chain telemetry — execution records, pattern detection, dependency discovery."""
from __future__ import annotations

import time

import pytest

from three_surgeons.core.chain_telemetry import (
    ExecutionRecord,
    ChainTelemetry,
    EvidenceGrade,
)
from three_surgeons.core.state import MemoryBackend


# ── ExecutionRecord ───────────────────────────────────────────────────

def test_execution_record_creation():
    rec = ExecutionRecord.create(
        chain_id="full-3s",
        segments_run=["pre-flight", "execute", "verify"],
        segments_skipped=["doc-flow"],
        success=True,
        duration_ms=1234.5,
        duration_by_segment={"pre-flight": 100, "execute": 900, "verify": 234.5},
        project_id="test-project",
    )
    assert rec.chain_id == "full-3s"
    assert rec.success
    assert len(rec.execution_id) == 12
    assert rec.order_digest  # non-empty hash


def test_execution_record_serialization():
    rec = ExecutionRecord.create(
        chain_id="test",
        segments_run=["a", "b"],
        segments_skipped=[],
        success=True,
        duration_ms=100,
        duration_by_segment={"a": 50, "b": 50},
    )
    serialized = rec.to_json()
    restored = ExecutionRecord.from_json(serialized)
    assert restored.chain_id == rec.chain_id
    assert restored.segments_run == rec.segments_run
    assert restored.execution_id == rec.execution_id


# ── ChainTelemetry ───────────────────────────────────────────────────

def test_record_and_retrieve_execution():
    state = MemoryBackend()
    tel = ChainTelemetry(state)

    rec = ExecutionRecord.create(
        chain_id="test-chain",
        segments_run=["a", "b"],
        segments_skipped=[],
        success=True,
        duration_ms=100,
        duration_by_segment={"a": 50, "b": 50},
    )
    tel.record(rec)

    recent = tel.recent_executions("test-chain", limit=5)
    assert len(recent) == 1
    assert recent[0].chain_id == "test-chain"


def test_pattern_detection_below_threshold():
    state = MemoryBackend()
    tel = ChainTelemetry(state)

    # Only 3 observations — below default threshold of 5
    for _ in range(3):
        rec = ExecutionRecord.create(
            chain_id="sparse",
            segments_run=["a", "b"],
            segments_skipped=[],
            success=True,
            duration_ms=100,
            duration_by_segment={"a": 50, "b": 50},
        )
        tel.record(rec)

    patterns = tel.detect_patterns("sparse")
    assert len(patterns) == 0


def test_pattern_detection_above_threshold():
    state = MemoryBackend()
    tel = ChainTelemetry(state)

    # 6 identical executions — above default threshold of 5
    for _ in range(6):
        rec = ExecutionRecord.create(
            chain_id="consistent",
            segments_run=["x", "y", "z"],
            segments_skipped=[],
            success=True,
            duration_ms=100,
            duration_by_segment={"x": 30, "y": 30, "z": 40},
        )
        tel.record(rec)

    patterns = tel.detect_patterns("consistent")
    assert len(patterns) >= 1


# ── Evidence grades ──────────────────────────────────────────────────

def test_evidence_grade_thresholds():
    assert EvidenceGrade.for_observations(3, 1.0) == EvidenceGrade.ANECDOTE
    assert EvidenceGrade.for_observations(10, 0.75) == EvidenceGrade.CORRELATION
    assert EvidenceGrade.for_observations(25, 0.90) == EvidenceGrade.CASE_SERIES
    assert EvidenceGrade.for_observations(55, 0.96) == EvidenceGrade.COHORT
