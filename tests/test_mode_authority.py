"""Tests for ModeAuthority — preset resolution, trigger detection, adaptive learning."""
from __future__ import annotations

import pytest

from three_surgeons.core.mode_authority import (
    PRESETS,
    ModeAuthority,
    Suggestion,
)
from three_surgeons.core.requirements import RuntimeContext
from three_surgeons.core.state import MemoryBackend


def _make_ctx(state=None, git_root=None) -> RuntimeContext:
    return RuntimeContext(
        healthy_llms=[],
        state=state or MemoryBackend(),
        evidence=None,
        git_available=git_root is not None,
        git_root=git_root,
        config=None,
    )


# ── Presets ───────────────────────────────────────────────────────────

def test_presets_exist():
    assert "full-3s" in PRESETS
    assert "lightweight" in PRESETS
    assert "plan-review" in PRESETS
    assert "evidence-dive" in PRESETS


def test_preset_lists_are_non_empty():
    for name, segments in PRESETS.items():
        assert len(segments) > 0, f"Preset '{name}' has no segments"


# ── Resolve ───────────────────────────────────────────────────────────

def test_resolve_returns_preset_segments():
    ma = ModeAuthority(MemoryBackend())
    segments = ma.resolve("lightweight", {})
    assert segments == list(PRESETS["lightweight"])


def test_resolve_with_disable_override():
    ma = ModeAuthority(MemoryBackend())
    overrides = {"verify": False}
    segments = ma.resolve("lightweight", overrides)
    assert "verify" not in segments


def test_resolve_with_enable_override():
    ma = ModeAuthority(MemoryBackend())
    overrides = {"extra-check": True}
    segments = ma.resolve("lightweight", overrides)
    assert "extra-check" in segments


def test_resolve_unknown_preset_raises():
    ma = ModeAuthority(MemoryBackend())
    with pytest.raises(KeyError):
        ma.resolve("nonexistent-mode", {})


# ── Suggest ───────────────────────────────────────────────────────────

def test_suggest_returns_none_when_no_trigger(tmp_path):
    ma = ModeAuthority(MemoryBackend())
    ctx = _make_ctx(git_root=str(tmp_path))
    suggestion = ma.suggest(ctx, "generic")
    assert suggestion is None


def test_suggest_plan_review_on_plan_trigger(tmp_path):
    # Create a plan file to trigger detection
    plans_dir = tmp_path / "docs" / "plans"
    plans_dir.mkdir(parents=True)
    (plans_dir / "2026-01-01-feature.md").write_text("# Plan")

    ma = ModeAuthority(MemoryBackend())
    ctx = _make_ctx(git_root=str(tmp_path))
    suggestion = ma.suggest(ctx, "plan_file_detected")
    assert suggestion is not None
    assert suggestion.mode == "plan-review"


# ── Adaptive learning ────────────────────────────────────────────────

def test_record_and_check_preference():
    state = MemoryBackend()
    ma = ModeAuthority(state)
    ma.record_preference("plan-review", accepted=True)
    ma.record_preference("plan-review", accepted=True)
    ma.record_preference("plan-review", accepted=False)

    stats = ma.get_preference_stats("plan-review")
    assert stats["accepted"] == 2
    assert stats["ignored"] == 1
