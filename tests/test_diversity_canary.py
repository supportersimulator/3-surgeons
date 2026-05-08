"""Tests for the QQ3 diversity canary.

Sidecar to INV-006 — these tests assert the canary's WHAT, not its HOW:
- yellow signals fire when surgeons collapse
- counters increment monotonically across calls
- ZSF — bad input never raises
- kill-switch (CONTEXT_DNA_DIVERSITY_CANARY=off) is reversible
- never affects consensus pass/fail (no exceptions, no return-code shifts)
"""
from __future__ import annotations

from dataclasses import dataclass

import pytest

from three_surgeons.core import diversity_canary
from three_surgeons.core.diversity_canary import (
    DIVERSITY_COUNTERS,
    evaluate_diversity,
    get_diversity_status,
    reset_diversity_counters,
)


@dataclass
class _SurgeonCfgStub:
    """Minimal stub matching the SurgeonConfig / LLMProvider attribute surface."""

    provider: str = ""
    model: str = ""
    endpoint: str = ""


@pytest.fixture(autouse=True)
def _reset_counters(monkeypatch: pytest.MonkeyPatch):
    """Each test starts with clean counters and the canary enabled."""
    monkeypatch.delenv("CONTEXT_DNA_DIVERSITY_CANARY", raising=False)
    reset_diversity_counters()
    yield
    reset_diversity_counters()


# ── Yellow signals ──────────────────────────────────────────────────


def test_same_provider_same_model_trips_yellow():
    """Both surgeons on deepseek/deepseek-chat → model collapse."""
    cardio_cfg = _SurgeonCfgStub(provider="deepseek", model="deepseek-chat")
    neuro_cfg = _SurgeonCfgStub(provider="deepseek", model="deepseek-chat")
    cardio_reply = {"text": "different text", "verdict": "agree", "caveats": ["a"]}
    neuro_reply = {"text": "another different text", "verdict": "agree", "caveats": ["b"]}

    out = evaluate_diversity(cardio_reply, neuro_reply, cardio_cfg, neuro_cfg)
    assert out["yellow"] is True
    assert any("model collapse" in r for r in out["reasons"])
    assert "deepseek/deepseek-chat" in out["reasons"][0]
    assert DIVERSITY_COUNTERS["same_provider_same_model"] == 1


def test_byte_identical_replies_trips_yellow():
    """Surgeons returned the exact same text → echo collapse."""
    cardio_cfg = _SurgeonCfgStub(provider="openai", model="gpt-4.1-mini")
    neuro_cfg = _SurgeonCfgStub(provider="deepseek", model="deepseek-chat")
    same = '{"confidence":0.9,"assessment":"agree"}'
    cardio_reply = {"text": same, "verdict": "agree", "caveats": ["caveat"]}
    neuro_reply = {"text": same, "verdict": "agree", "caveats": ["caveat"]}

    out = evaluate_diversity(cardio_reply, neuro_reply, cardio_cfg, neuro_cfg)
    assert out["yellow"] is True
    assert any("byte-identical" in r for r in out["reasons"])
    assert DIVERSITY_COUNTERS["byte_identical_replies"] == 1


def test_frictionless_agreement_trips_yellow():
    """Both agree, zero caveats → suspiciously frictionless."""
    cardio_cfg = _SurgeonCfgStub(provider="openai", model="gpt-4.1-mini")
    neuro_cfg = _SurgeonCfgStub(provider="mlx", model="qwen3-4b")
    cardio_reply = {"text": "different cardio reasoning", "verdict": "agree", "caveats": []}
    neuro_reply = {"text": "different neuro reasoning", "verdict": "agree", "caveats": []}

    out = evaluate_diversity(cardio_reply, neuro_reply, cardio_cfg, neuro_cfg)
    assert out["yellow"] is True
    assert any("frictionless" in r for r in out["reasons"])
    assert DIVERSITY_COUNTERS["verdict_agree_no_caveats"] == 1


# ── Healthy / no-yellow paths ───────────────────────────────────────


def test_distinct_providers_with_caveats_no_yellow():
    """Healthy diversity: different providers, both agree but with caveats."""
    cardio_cfg = _SurgeonCfgStub(provider="openai", model="gpt-4.1-mini")
    neuro_cfg = _SurgeonCfgStub(provider="mlx", model="qwen3-4b")
    cardio_reply = {"text": "cardio analysis", "verdict": "agree", "caveats": ["edge case X"]}
    neuro_reply = {"text": "neuro analysis", "verdict": "agree", "caveats": ["edge case Y"]}

    out = evaluate_diversity(cardio_reply, neuro_reply, cardio_cfg, neuro_cfg)
    assert out["yellow"] is False
    assert out["reasons"] == []
    assert DIVERSITY_COUNTERS["yellow_signals_total"] == 0


def test_disagreement_no_yellow():
    """Surgeons disagreeing — exactly the friction we WANT — never yellow."""
    cardio_cfg = _SurgeonCfgStub(provider="openai", model="gpt-4.1-mini")
    neuro_cfg = _SurgeonCfgStub(provider="deepseek", model="deepseek-chat")
    cardio_reply = {"text": "yes", "verdict": "agree", "caveats": []}
    neuro_reply = {"text": "no", "verdict": "disagree", "caveats": []}

    out = evaluate_diversity(cardio_reply, neuro_reply, cardio_cfg, neuro_cfg)
    assert out["yellow"] is False


# ── Counter monotonicity across multiple probes ─────────────────────


def test_counters_increment_across_probes():
    """consensus_total bumps every call; yellow_signals_total only on yellow."""
    cardio_cfg_collapse = _SurgeonCfgStub(provider="deepseek", model="deepseek-chat")
    neuro_cfg_collapse = _SurgeonCfgStub(provider="deepseek", model="deepseek-chat")
    cardio_cfg_diverse = _SurgeonCfgStub(provider="openai", model="gpt-4.1-mini")
    neuro_cfg_diverse = _SurgeonCfgStub(provider="mlx", model="qwen3-4b")

    diverse_reply_a = {"text": "a", "verdict": "agree", "caveats": ["x"]}
    diverse_reply_b = {"text": "b", "verdict": "disagree", "caveats": []}
    collapse_reply_a = {"text": "alpha", "verdict": "agree", "caveats": ["x"]}
    collapse_reply_b = {"text": "beta", "verdict": "agree", "caveats": ["y"]}

    # 3 collapsed calls + 2 healthy calls = 5 probes, 3 yellow signals
    for _ in range(3):
        evaluate_diversity(
            collapse_reply_a, collapse_reply_b, cardio_cfg_collapse, neuro_cfg_collapse
        )
    for _ in range(2):
        evaluate_diversity(
            diverse_reply_a, diverse_reply_b, cardio_cfg_diverse, neuro_cfg_diverse
        )

    assert DIVERSITY_COUNTERS["consensus_total"] == 5
    assert DIVERSITY_COUNTERS["same_provider_same_model"] == 3
    assert DIVERSITY_COUNTERS["yellow_signals_total"] == 3
    assert DIVERSITY_COUNTERS["byte_identical_replies"] == 0


def test_multiple_signals_count_once_per_call():
    """A single call that trips two signals bumps yellow_signals_total by ONE."""
    cardio_cfg = _SurgeonCfgStub(provider="deepseek", model="deepseek-chat")
    neuro_cfg = _SurgeonCfgStub(provider="deepseek", model="deepseek-chat")
    same = "identical"
    cardio_reply = {"text": same, "verdict": "agree", "caveats": []}
    neuro_reply = {"text": same, "verdict": "agree", "caveats": []}

    out = evaluate_diversity(cardio_reply, neuro_reply, cardio_cfg, neuro_cfg)
    assert out["yellow"] is True
    # All three signals trip this call
    assert len(out["reasons"]) == 3
    # But yellow_signals_total only ticks once per call
    assert DIVERSITY_COUNTERS["yellow_signals_total"] == 1
    assert DIVERSITY_COUNTERS["consensus_total"] == 1


# ── ZSF / robustness ────────────────────────────────────────────────


def test_none_inputs_never_raise():
    """ZSF: None replies/configs return clean no-yellow result."""
    out = evaluate_diversity(None, None, None, None)
    assert out["yellow"] is False
    assert out["reasons"] == []
    assert DIVERSITY_COUNTERS["consensus_total"] == 1


def test_malformed_replies_never_raise():
    """ZSF: non-dict replies are coerced, no exception escapes."""
    cardio_cfg = _SurgeonCfgStub(provider="openai", model="gpt-4.1-mini")
    neuro_cfg = _SurgeonCfgStub(provider="deepseek", model="deepseek-chat")

    # Replies as strings (wrong type), caveats as int (wrong type)
    out = evaluate_diversity(
        "not a dict",  # type: ignore[arg-type]
        {"caveats": 42, "verdict": None},
        cardio_cfg,
        neuro_cfg,
    )
    assert out["yellow"] is False
    # consensus_total still incremented — telemetry stays honest
    assert DIVERSITY_COUNTERS["consensus_total"] == 1


# ── Kill-switch reversibility ───────────────────────────────────────


def test_kill_switch_disables_emission(monkeypatch: pytest.MonkeyPatch):
    """CONTEXT_DNA_DIVERSITY_CANARY=off → no reasons emitted, no yellow."""
    monkeypatch.setenv("CONTEXT_DNA_DIVERSITY_CANARY", "off")
    cardio_cfg = _SurgeonCfgStub(provider="deepseek", model="deepseek-chat")
    neuro_cfg = _SurgeonCfgStub(provider="deepseek", model="deepseek-chat")
    cardio_reply = {"text": "x", "verdict": "agree", "caveats": []}
    neuro_reply = {"text": "x", "verdict": "agree", "caveats": []}

    out = evaluate_diversity(cardio_reply, neuro_reply, cardio_cfg, neuro_cfg)
    assert out["yellow"] is False
    assert out["reasons"] == []
    # consensus_total still bumps — rate-of-evaluation telemetry unaffected.
    assert DIVERSITY_COUNTERS["consensus_total"] == 1
    assert DIVERSITY_COUNTERS["yellow_signals_total"] == 0


def test_kill_switch_status_flag(monkeypatch: pytest.MonkeyPatch):
    """get_diversity_status() reports enabled=False when kill-switch active."""
    monkeypatch.setenv("CONTEXT_DNA_DIVERSITY_CANARY", "off")
    status = get_diversity_status()
    assert status["enabled"] is False

    monkeypatch.delenv("CONTEXT_DNA_DIVERSITY_CANARY", raising=False)
    status = get_diversity_status()
    assert status["enabled"] is True


# ── Sidecar contract — does NOT affect consensus pass/fail ──────────


def test_canary_does_not_raise_with_provider_object_shape():
    """LLMProvider exposes ._provider not .provider — canary must handle both."""

    class _LLMProviderLike:
        def __init__(self, p: str, m: str) -> None:
            self._provider = p
            self.model = m

    cardio = _LLMProviderLike("deepseek", "deepseek-chat")
    neuro = _LLMProviderLike("deepseek", "deepseek-chat")
    cardio_reply = {"text": "a", "verdict": "agree", "caveats": ["x"]}
    neuro_reply = {"text": "b", "verdict": "agree", "caveats": ["y"]}

    out = evaluate_diversity(cardio_reply, neuro_reply, cardio, neuro)
    # Falls through to ._provider; should still detect collapse
    assert out["yellow"] is True
    assert any("model collapse" in r for r in out["reasons"])


def test_get_diversity_status_returns_independent_snapshot():
    """Mutating the snapshot must not corrupt the live counters."""
    evaluate_diversity({}, {}, None, None)
    snap = get_diversity_status()
    snap["counters"]["consensus_total"] = 999
    assert DIVERSITY_COUNTERS["consensus_total"] == 1
