"""Tests for surgeon consultation and community chain sync."""
from __future__ import annotations

import json

import pytest

from three_surgeons.core.chain_consultation import (
    ChainConsultation,
    CommunityPreset,
    should_consult,
)
from three_surgeons.core.state import MemoryBackend


# ── Consultation cadence ──────────────────────────────────────────────

def test_should_not_consult_below_cadence():
    state = MemoryBackend()
    assert not should_consult(state, cadence=20)


def test_should_consult_at_cadence():
    state = MemoryBackend()
    # Simulate 20 executions
    state.set("chain:total_executions", "20")
    state.set("chain:last_consultation_at", "0")
    assert should_consult(state, cadence=20)


def test_should_not_consult_when_recently_consulted():
    state = MemoryBackend()
    state.set("chain:total_executions", "40")
    state.set("chain:last_consultation_at", "20")
    assert should_consult(state, cadence=20)

    state.set("chain:last_consultation_at", "30")
    assert not should_consult(state, cadence=20)


# ── CommunityPreset ──────────────────────────────────────────────────

def test_community_preset_to_yaml():
    preset = CommunityPreset(
        name="api-hardening",
        segments=["pre-flight", "contradiction-scan", "risk-scan", "verify"],
        evidence_grade="case_series",
        observations=34,
        surgeon_consensus=0.87,
        discovered_by="auto-pattern-detection",
        tags=["api", "security"],
    )
    yaml_str = preset.to_yaml()
    assert "api-hardening" in yaml_str
    assert "pre-flight" in yaml_str
    assert "case_series" in yaml_str


def test_community_preset_from_yaml():
    yaml_str = """name: api-hardening
segments:
  - pre-flight
  - verify
evidence_grade: correlation
observations: 10
surgeon_consensus: 0.75
discovered_by: manual
tags:
  - api
"""
    preset = CommunityPreset.from_yaml(yaml_str)
    assert preset.name == "api-hardening"
    assert preset.segments == ["pre-flight", "verify"]
    assert preset.observations == 10


# ── ChainConsultation ────────────────────────────────────────────────

def test_consultation_generates_summary():
    state = MemoryBackend()
    consultation = ChainConsultation(state)
    summary = consultation.build_consultation_context(
        available_segments=["pre-flight", "execute", "verify", "doc-flow"],
        current_presets={"lightweight": ["pre-flight", "execute", "verify"]},
        recent_failures=[],
    )
    assert "pre-flight" in summary
    assert "lightweight" in summary
