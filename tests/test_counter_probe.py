"""Tests for the SS1 counter-probe demotion gate.

Contract:
- Both surgeons agreeing with BOTH a claim and its negation at conf>=0.7
  → ``sycophantic=True`` and ``effective_score`` demoted to 0.0.
- Both surgeons flipping correctly (agree on claim, disagree on negation
  or the reverse) → ``genuine=True`` and confidence boosted +10%.
- Exactly one surgeon flipping → ``single_flip=True`` and confidence
  reduced 30%.
- All abstain on both → ``no_signal=True``; not sycophantic.
- Default behaviour unchanged: counter_probe disabled by default — no
  perf regression on the existing ``team.consensus()`` path.
"""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from three_surgeons.core.counter_probe import (
    CONFIDENCE_BOOST,
    CONFIDENCE_REDUCTION,
    COUNTER_PROBE_COUNTERS,
    apply_to_result,
    detect_sycophancy,
    is_enabled,
    negate_claim,
    rate_limited,
    reset_counter_probe_counters,
)
from three_surgeons.core.cross_exam import ConsensusResult, SurgeryTeam
from three_surgeons.core.evidence import EvidenceStore
from three_surgeons.core.models import LLMResponse
from three_surgeons.core.state import MemoryBackend


# ── Fixtures ────────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def _reset_counters(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("CONTEXT_DNA_CONSENSUS_COUNTER_PROBE", raising=False)
    reset_counter_probe_counters()
    yield
    reset_counter_probe_counters()


def _consensus_result(
    *,
    cardio_assessment: str,
    cardio_conf: float,
    neuro_assessment: str,
    neuro_conf: float,
    weighted_score: float = 0.0,
    total_cost: float = 0.0,
) -> ConsensusResult:
    """Build a ConsensusResult stub matching the production shape."""
    r = ConsensusResult(claim="test claim")
    r.cardiologist_assessment = cardio_assessment
    r.cardiologist_confidence = cardio_conf
    r.neurologist_assessment = neuro_assessment
    r.neurologist_confidence = neuro_conf
    r.weighted_score = weighted_score
    r.total_cost = total_cost
    return r


# ── negate_claim ────────────────────────────────────────────────────


def test_negate_claim_prefixes_negation():
    out = negate_claim("Aaron should ship 3-surgeons standalone first")
    assert out.startswith("It is NOT the case that")
    assert "ship 3-surgeons" in out
    assert out.endswith(".")


def test_negate_claim_strips_trailing_punctuation():
    out = negate_claim("ship the gate now!!")
    assert "ship the gate now" in out
    assert "!!" not in out


def test_negate_claim_empty_input_returns_empty_and_bumps_counter():
    assert negate_claim("") == ""
    assert COUNTER_PROBE_COUNTERS["negation_failures"] >= 1


def test_negate_claim_none_input_never_raises():
    # ZSF: None coerces cleanly to ""
    assert negate_claim(None) == ""  # type: ignore[arg-type]
    assert COUNTER_PROBE_COUNTERS["negation_failures"] >= 1


# ── detect_sycophancy: each rule ────────────────────────────────────


def test_both_agree_both_directions_is_sycophantic():
    """RR5 finding: both surgeons agree with claim AND ¬claim at conf>=0.7."""
    primary = _consensus_result(
        cardio_assessment="agree", cardio_conf=0.95,
        neuro_assessment="agree", neuro_conf=0.95,
        weighted_score=1.0,
    )
    negated = _consensus_result(
        cardio_assessment="agree", cardio_conf=0.95,
        neuro_assessment="agree", neuro_conf=0.95,
        weighted_score=1.0,
    )
    verdict = detect_sycophancy(primary, negated)
    assert verdict["sycophantic"] is True
    assert verdict["genuine"] is False
    assert verdict["demotion"] == 0.0
    assert "sycophantic" in verdict["reason"].lower() or "agreed with claim AND" in verdict["reason"]


def test_both_flip_correctly_is_genuine():
    """Both surgeons agree on claim and disagree on negation → genuine."""
    primary = _consensus_result(
        cardio_assessment="agree", cardio_conf=0.9,
        neuro_assessment="agree", neuro_conf=0.85,
        weighted_score=1.0,
    )
    negated = _consensus_result(
        cardio_assessment="disagree", cardio_conf=0.9,
        neuro_assessment="disagree", neuro_conf=0.85,
        weighted_score=-1.0,
    )
    verdict = detect_sycophancy(primary, negated)
    assert verdict["genuine"] is True
    assert verdict["sycophantic"] is False
    assert verdict["demotion"] == 1.0
    assert verdict["confidence_delta"] == pytest.approx(CONFIDENCE_BOOST)


def test_only_one_flips_is_single_flip():
    """Cardiologist flips correctly; neurologist agrees with both."""
    primary = _consensus_result(
        cardio_assessment="agree", cardio_conf=0.9,
        neuro_assessment="agree", neuro_conf=0.9,
        weighted_score=1.0,
    )
    negated = _consensus_result(
        cardio_assessment="disagree", cardio_conf=0.85,
        neuro_assessment="agree", neuro_conf=0.9,
        weighted_score=0.0,
    )
    verdict = detect_sycophancy(primary, negated)
    assert verdict["single_flip"] is True
    assert verdict["sycophantic"] is False
    assert verdict["genuine"] is False
    assert verdict["confidence_delta"] == pytest.approx(-CONFIDENCE_REDUCTION)
    assert "cardiologist" in verdict["reason"].lower()


def test_all_abstain_is_no_signal():
    """Both surgeons unavailable on both probes → no_signal, not sycophantic."""
    primary = _consensus_result(
        cardio_assessment="unavailable", cardio_conf=0.0,
        neuro_assessment="unavailable", neuro_conf=0.0,
    )
    negated = _consensus_result(
        cardio_assessment="unavailable", cardio_conf=0.0,
        neuro_assessment="unavailable", neuro_conf=0.0,
    )
    verdict = detect_sycophancy(primary, negated)
    assert verdict["no_signal"] is True
    assert verdict["sycophantic"] is False
    assert verdict["demotion"] == 1.0


def test_uncertain_on_both_is_no_signal():
    """``uncertain`` is treated as abstain — not a flip."""
    primary = _consensus_result(
        cardio_assessment="uncertain", cardio_conf=0.5,
        neuro_assessment="uncertain", neuro_conf=0.5,
    )
    negated = _consensus_result(
        cardio_assessment="uncertain", cardio_conf=0.5,
        neuro_assessment="uncertain", neuro_conf=0.5,
    )
    verdict = detect_sycophancy(primary, negated)
    assert verdict["no_signal"] is True


def test_low_confidence_agreement_does_not_trip_sycophancy():
    """Confidence below 0.7 is below the threshold → not classified."""
    primary = _consensus_result(
        cardio_assessment="agree", cardio_conf=0.4,
        neuro_assessment="agree", neuro_conf=0.4,
    )
    negated = _consensus_result(
        cardio_assessment="agree", cardio_conf=0.4,
        neuro_assessment="agree", neuro_conf=0.4,
    )
    verdict = detect_sycophancy(primary, negated)
    assert verdict["sycophantic"] is False


def test_threshold_override():
    """Caller can raise threshold to require very high confidence."""
    primary = _consensus_result(
        cardio_assessment="agree", cardio_conf=0.75,
        neuro_assessment="agree", neuro_conf=0.75,
    )
    negated = _consensus_result(
        cardio_assessment="agree", cardio_conf=0.75,
        neuro_assessment="agree", neuro_conf=0.75,
    )
    # Default threshold (0.7): would trip
    assert detect_sycophancy(primary, negated)["sycophantic"] is True
    # Raised threshold (0.9): does not trip
    assert detect_sycophancy(primary, negated, threshold=0.9)["sycophantic"] is False


# ── apply_to_result ─────────────────────────────────────────────────


def test_apply_demotes_score_on_sycophancy():
    primary = _consensus_result(
        cardio_assessment="agree", cardio_conf=0.95,
        neuro_assessment="agree", neuro_conf=0.95,
        weighted_score=1.0, total_cost=0.001,
    )
    negated = _consensus_result(
        cardio_assessment="agree", cardio_conf=0.95,
        neuro_assessment="agree", neuro_conf=0.95,
        weighted_score=1.0, total_cost=0.001,
    )
    apply_to_result(primary, negated, negation="It is NOT the case that ...")
    assert primary.sycophantic is True
    assert primary.effective_score == 0.0
    assert primary.counter_probe_active is True
    assert primary.counter_probe_negation.startswith("It is NOT the case")
    # Cost is rolled up.
    assert primary.total_cost == pytest.approx(0.002)
    assert COUNTER_PROBE_COUNTERS["sycophantic_detected"] == 1


def test_apply_preserves_score_on_genuine():
    primary = _consensus_result(
        cardio_assessment="agree", cardio_conf=0.85,
        neuro_assessment="agree", neuro_conf=0.85,
        weighted_score=0.85,
    )
    negated = _consensus_result(
        cardio_assessment="disagree", cardio_conf=0.85,
        neuro_assessment="disagree", neuro_conf=0.85,
        weighted_score=-0.85,
    )
    apply_to_result(primary, negated)
    assert primary.sycophantic is False
    assert primary.counter_probe_genuine is True
    assert primary.effective_score == pytest.approx(0.85)
    # Boosted confidence (clamped to [0,1]).
    assert primary.cardiologist_confidence_adjusted == pytest.approx(
        min(1.0, 0.85 + CONFIDENCE_BOOST)
    )
    assert COUNTER_PROBE_COUNTERS["genuine_consensus"] == 1


def test_apply_reduces_confidence_on_single_flip():
    primary = _consensus_result(
        cardio_assessment="agree", cardio_conf=0.9,
        neuro_assessment="agree", neuro_conf=0.9,
        weighted_score=1.0,
    )
    negated = _consensus_result(
        cardio_assessment="disagree", cardio_conf=0.9,
        neuro_assessment="agree", neuro_conf=0.9,
        weighted_score=0.0,
    )
    apply_to_result(primary, negated)
    assert primary.counter_probe_single_flip is True
    assert primary.effective_score == pytest.approx(1.0)
    # Confidence reduced 30% additive
    assert primary.cardiologist_confidence_adjusted == pytest.approx(
        max(0.0, 0.9 - CONFIDENCE_REDUCTION)
    )
    assert COUNTER_PROBE_COUNTERS["single_flip"] == 1


# ── is_enabled ──────────────────────────────────────────────────────


def test_is_enabled_default_off():
    assert is_enabled() is False
    assert is_enabled(False) is False


def test_is_enabled_with_flag():
    assert is_enabled(True) is True


def test_is_enabled_with_env(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("CONTEXT_DNA_CONSENSUS_COUNTER_PROBE", "on")
    assert is_enabled() is True
    monkeypatch.setenv("CONTEXT_DNA_CONSENSUS_COUNTER_PROBE", "1")
    assert is_enabled() is True
    monkeypatch.setenv("CONTEXT_DNA_CONSENSUS_COUNTER_PROBE", "true")
    assert is_enabled() is True
    monkeypatch.setenv("CONTEXT_DNA_CONSENSUS_COUNTER_PROBE", "off")
    assert is_enabled() is False


# ── rate_limited ────────────────────────────────────────────────────


def test_rate_limit_idempotent_same_claim():
    assert rate_limited("same claim") is False
    # Immediate second call within 1s window
    assert rate_limited("same claim") is True
    assert COUNTER_PROBE_COUNTERS["rate_limited"] == 1


def test_rate_limit_different_claims_independent():
    assert rate_limited("claim A") is False
    assert rate_limited("claim B") is False


# ── End-to-end via SurgeryTeam.consensus(counter_probe=True) ────────


def _make_team(cardio_responses, neuro_responses, tmp_path):
    """Build a SurgeryTeam where each surgeon returns from a queue.

    The neuro_responses[1] / cardio_responses[1] entries are returned for
    the negation pass.
    """
    cardio = MagicMock()
    cardio.query.side_effect = cardio_responses
    neuro = MagicMock()
    neuro.query.side_effect = neuro_responses
    evidence = EvidenceStore(str(tmp_path / "evidence.db"))
    return SurgeryTeam(
        cardiologist=cardio,
        neurologist=neuro,
        evidence=evidence,
        state=MemoryBackend(),
    )


def _resp(content: str, model: str = "deepseek-chat", cost: float = 0.001) -> LLMResponse:
    return LLMResponse(
        ok=True, content=content, latency_ms=50, model=model, cost_usd=cost
    )


def test_default_consensus_unchanged_no_counter_probe(tmp_path):
    """Default behaviour: counter_probe off → no negation pass, no fields set."""
    cardio_resps = [_resp('{"confidence": 0.9, "assessment": "agree"}')]
    neuro_resps = [_resp('{"confidence": 0.9, "assessment": "agree"}')]
    team = _make_team(cardio_resps, neuro_resps, tmp_path)

    result = team.consensus("test claim")
    assert result.counter_probe_active is False
    assert result.sycophantic is False
    # weighted_score and effective_score are equal when gate is off
    assert result.effective_score == pytest.approx(result.weighted_score)


def test_consensus_with_counter_probe_detects_sycophancy(tmp_path):
    """Live e2e: both surgeons agree on claim and negation → demoted."""
    # 4 calls total: cardio claim, neuro claim, cardio negation, neuro negation
    cardio_resps = [
        _resp('{"confidence": 0.95, "assessment": "agree"}'),
        _resp('{"confidence": 0.95, "assessment": "agree"}'),
    ]
    neuro_resps = [
        _resp('{"confidence": 0.95, "assessment": "agree"}'),
        _resp('{"confidence": 0.95, "assessment": "agree"}'),
    ]
    team = _make_team(cardio_resps, neuro_resps, tmp_path)

    result = team.consensus("Aaron should ship X first", counter_probe=True)
    assert result.counter_probe_active is True
    assert result.sycophantic is True
    assert result.weighted_score == pytest.approx(1.0)
    assert result.effective_score == 0.0
    # Cost rolled up.
    assert result.total_cost == pytest.approx(0.004)
    assert "sycophantic" in result.counter_probe_reason.lower() or "agreed with claim" in result.counter_probe_reason


def test_consensus_with_counter_probe_genuine_passes_through(tmp_path):
    """Surgeons flip correctly → genuine, no demotion."""
    cardio_resps = [
        _resp('{"confidence": 0.9, "assessment": "agree"}'),
        _resp('{"confidence": 0.9, "assessment": "disagree"}'),
    ]
    neuro_resps = [
        _resp('{"confidence": 0.9, "assessment": "agree"}'),
        _resp('{"confidence": 0.9, "assessment": "disagree"}'),
    ]
    team = _make_team(cardio_resps, neuro_resps, tmp_path)

    result = team.consensus("genuinely correct claim", counter_probe=True)
    assert result.counter_probe_active is True
    assert result.sycophantic is False
    assert result.counter_probe_genuine is True
    assert result.effective_score == pytest.approx(result.weighted_score)


def test_consensus_env_var_activation(tmp_path, monkeypatch: pytest.MonkeyPatch):
    """``CONTEXT_DNA_CONSENSUS_COUNTER_PROBE=on`` activates the gate even
    when the kwarg is False — the env var is the global escape hatch.
    Both surgeons agree → 4 calls (claim+negation), gate marks active.
    """
    monkeypatch.setenv("CONTEXT_DNA_CONSENSUS_COUNTER_PROBE", "on")
    cardio_resps = [
        _resp('{"confidence": 0.9, "assessment": "agree"}'),
        _resp('{"confidence": 0.9, "assessment": "disagree"}'),
    ]
    neuro_resps = [
        _resp('{"confidence": 0.9, "assessment": "agree"}'),
        _resp('{"confidence": 0.9, "assessment": "disagree"}'),
    ]
    team = _make_team(cardio_resps, neuro_resps, tmp_path)

    result = team.consensus("env-activated claim")
    assert result.counter_probe_active is True
    assert result.counter_probe_genuine is True


def test_consensus_env_var_off_no_activation(tmp_path, monkeypatch: pytest.MonkeyPatch):
    """When env var is unset and kwarg is default, gate stays OFF — protects
    the library default invocation path (no perf regression).
    """
    monkeypatch.delenv("CONTEXT_DNA_CONSENSUS_COUNTER_PROBE", raising=False)
    cardio_resps = [_resp('{"confidence": 0.9, "assessment": "agree"}')]
    neuro_resps = [_resp('{"confidence": 0.9, "assessment": "agree"}')]
    team = _make_team(cardio_resps, neuro_resps, tmp_path)

    result = team.consensus("test claim")
    assert result.counter_probe_active is False
    # Only 2 calls — no negation pass.
    assert team._cardiologist.query.call_count == 1
    assert team._neurologist.query.call_count == 1


def test_negation_failure_falls_back_safely(tmp_path, monkeypatch: pytest.MonkeyPatch):
    """ZSF: negate_claim returning empty → gate skipped, no crash."""
    cardio_resps = [_resp('{"confidence": 0.9, "assessment": "agree"}')]
    neuro_resps = [_resp('{"confidence": 0.9, "assessment": "agree"}')]
    team = _make_team(cardio_resps, neuro_resps, tmp_path)

    monkeypatch.setattr(
        "three_surgeons.core.counter_probe.negate_claim", lambda c: ""
    )
    result = team.consensus("test claim", counter_probe=True)
    # Gate skipped — counter_probe_active stays False, no crash.
    assert result.counter_probe_active is False


def test_no_recursion_on_negation_pass(tmp_path):
    """Internal: the negation pass must NOT itself trigger another probe."""
    # 4 calls if no recursion; >4 means recursion happened.
    cardio_resps = [
        _resp('{"confidence": 0.9, "assessment": "agree"}'),
        _resp('{"confidence": 0.9, "assessment": "disagree"}'),
    ]
    neuro_resps = [
        _resp('{"confidence": 0.9, "assessment": "agree"}'),
        _resp('{"confidence": 0.9, "assessment": "disagree"}'),
    ]
    team = _make_team(cardio_resps, neuro_resps, tmp_path)
    result = team.consensus("claim", counter_probe=True)
    assert result.counter_probe_active is True
    # Each surgeon should have been called exactly twice (claim + negation).
    assert team._cardiologist.query.call_count == 2
    assert team._neurologist.query.call_count == 2
