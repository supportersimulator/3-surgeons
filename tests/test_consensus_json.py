"""Tests for ``3s consensus --json`` (ZZ3 / WW5 ship).

Contract:
- ``--json`` emits a single, well-formed JSON object on stdout.
- Schema includes the keys the classifier needs: claim, cardio.{verdict,confidence},
  neuro.{verdict,confidence}, weighted_score, effective_score, sycophantic,
  counter_probe_active, diversity_yellow, cost_usd (+ counter-probe details).
- Default prose output is unchanged when ``--json`` is NOT passed (regression
  guard for downstream parsers).
- Counter-probe interaction: when ``--counter-probe`` (or env var) activates
  the gate, ``counter_probe_active=True`` and the negation-side fields are
  populated in the JSON payload.
- Stdout stays JSON-only: warnings/diagnostics route to stderr so a single
  ``json.loads(stdout)`` always succeeds.
- ZSF: serialization failure still emits a well-formed JSON envelope with an
  ``error`` key (never crashes the CLI, never leaks prose to stdout).
"""
from __future__ import annotations

import json
from unittest.mock import patch

import pytest
from click.testing import CliRunner

from three_surgeons.cli.main import cli
from three_surgeons.core.cross_exam import ConsensusResult


# ── Helpers ──────────────────────────────────────────────────────────


def _stub_result(
    *,
    claim: str = "test claim",
    cardio_assessment: str = "agree",
    cardio_conf: float = 0.9,
    neuro_assessment: str = "agree",
    neuro_conf: float = 0.85,
    weighted_score: float = 1.0,
    total_cost: float = 0.0002,
    counter_probe_active: bool = False,
    sycophantic: bool = False,
    counter_probe_negation: str = "",
    counter_probe_negation_score: float = 0.0,
    counter_probe_cost: float = 0.0,
    counter_probe_reason: str = "",
    diversity_yellow: bool = False,
    diversity_reasons=None,
) -> ConsensusResult:
    """Build a ConsensusResult mock matching the production shape."""
    r = ConsensusResult(claim=claim)
    r.cardiologist_assessment = cardio_assessment
    r.cardiologist_confidence = cardio_conf
    r.neurologist_assessment = neuro_assessment
    r.neurologist_confidence = neuro_conf
    r.weighted_score = weighted_score
    r.effective_score = weighted_score if not sycophantic else 0.0
    r.total_cost = total_cost
    r.counter_probe_active = counter_probe_active
    r.sycophantic = sycophantic
    r.counter_probe_negation = counter_probe_negation
    r.counter_probe_negation_score = counter_probe_negation_score
    r.counter_probe_cost = counter_probe_cost
    r.counter_probe_reason = counter_probe_reason
    r.diversity_yellow = diversity_yellow
    r.diversity_reasons = list(diversity_reasons or [])
    return r


def _invoke_consensus(args, *, result):
    """Run ``3s consensus <args>`` with SurgeryTeam.consensus stubbed."""
    # Click 8.3 CliRunner separates stdout/stderr by default — no constructor flag.
    runner = CliRunner()
    # Patch everything the CLI touches before SurgeryTeam.consensus is called.
    with patch("three_surgeons.cli.main.LLMProvider"), \
         patch("three_surgeons.cli.main.EvidenceStore"), \
         patch("three_surgeons.cli.main.create_backend_from_config"), \
         patch("three_surgeons.cli.main._make_neuro"), \
         patch(
             "three_surgeons.core.cross_exam.SurgeryTeam.consensus",
             return_value=result,
         ):
        return runner.invoke(cli, ["consensus", *args])


# ── --json basic shape ───────────────────────────────────────────────


def test_json_flag_emits_valid_json():
    result = _stub_result()
    cli_result = _invoke_consensus(["--json", "test claim"], result=result)
    assert cli_result.exit_code == 0, cli_result.output
    # stdout MUST be parseable as a single JSON object.
    payload = json.loads(cli_result.stdout)
    assert isinstance(payload, dict)


def test_json_flag_all_expected_keys_present():
    """The schema documented in ZZ3 — every key the classifier needs."""
    result = _stub_result(
        counter_probe_active=True,
        counter_probe_negation="It is NOT the case that test.",
        counter_probe_negation_score=-0.5,
        counter_probe_cost=0.0001,
    )
    cli_result = _invoke_consensus(
        ["--json", "--counter-probe", "test claim"], result=result
    )
    payload = json.loads(cli_result.stdout)

    expected_keys = {
        "claim",
        "cardio",
        "neuro",
        "weighted_score",
        "effective_score",
        "sycophantic",
        "counter_probe_active",
        "counter_probe_negation",
        "counter_probe_negation_score",
        "counter_probe_cost",
        "counter_probe_reason",
        "counter_probe_genuine",
        "counter_probe_single_flip",
        "counter_probe_no_signal",
        "diversity_yellow",
        "diversity_reasons",
        "cost_usd",
    }
    missing = expected_keys - set(payload.keys())
    assert not missing, f"JSON payload missing keys: {missing}"
    # Nested verdict objects.
    assert {"verdict", "confidence"} <= set(payload["cardio"].keys())
    assert {"verdict", "confidence"} <= set(payload["neuro"].keys())


def test_json_field_values_round_trip():
    """Field values must reflect the underlying ConsensusResult faithfully."""
    result = _stub_result(
        claim="ship X first",
        cardio_assessment="agree",
        cardio_conf=0.92,
        neuro_assessment="disagree",
        neuro_conf=0.81,
        weighted_score=0.11,
        total_cost=0.0007,
    )
    cli_result = _invoke_consensus(["--json", "ship X first"], result=result)
    payload = json.loads(cli_result.stdout)
    assert payload["claim"] == "ship X first"
    assert payload["cardio"]["verdict"] == "agree"
    assert payload["cardio"]["confidence"] == pytest.approx(0.92)
    assert payload["neuro"]["verdict"] == "disagree"
    assert payload["neuro"]["confidence"] == pytest.approx(0.81)
    assert payload["weighted_score"] == pytest.approx(0.11)
    assert payload["cost_usd"] == pytest.approx(0.0007)


# ── Default prose output unchanged when --json absent ───────────────


def test_default_output_unchanged_without_json_flag():
    """Regression guard: prose output preserved for existing callers."""
    result = _stub_result()
    cli_result = _invoke_consensus(["test claim"], result=result)
    assert cli_result.exit_code == 0, cli_result.output
    # Prose output uses these stable markers.
    assert "Consensus on:" in cli_result.stdout
    assert "Cardiologist:" in cli_result.stdout
    assert "Weighted score:" in cli_result.stdout
    # Stdout is NOT valid JSON (sanity: prose path != JSON path).
    with pytest.raises(json.JSONDecodeError):
        json.loads(cli_result.stdout)


# ── Counter-probe interaction ────────────────────────────────────────


def test_json_with_counter_probe_active_surfaces_gate_fields():
    """--json + --counter-probe → JSON includes counter_probe_active=True."""
    result = _stub_result(
        counter_probe_active=True,
        sycophantic=True,
        counter_probe_negation="It is NOT the case that ship X first.",
        counter_probe_negation_score=0.9,
        counter_probe_cost=0.0001,
        counter_probe_reason="both surgeons agreed with claim AND its negation",
    )
    cli_result = _invoke_consensus(
        ["--json", "--counter-probe", "ship X first"], result=result
    )
    payload = json.loads(cli_result.stdout)
    assert payload["counter_probe_active"] is True
    assert payload["sycophantic"] is True
    # Demotion: effective_score=0.0 even though weighted_score=1.0.
    assert payload["weighted_score"] == pytest.approx(1.0)
    assert payload["effective_score"] == 0.0
    assert "agreed with claim" in payload["counter_probe_reason"]


def test_json_without_counter_probe_marks_gate_inactive():
    """No --counter-probe and no env var → counter_probe_active=False."""
    result = _stub_result(counter_probe_active=False, sycophantic=False)
    cli_result = _invoke_consensus(["--json", "neutral claim"], result=result)
    payload = json.loads(cli_result.stdout)
    assert payload["counter_probe_active"] is False
    assert payload["sycophantic"] is False


def test_json_counter_probe_env_var_activates_gate(
    monkeypatch: pytest.MonkeyPatch,
):
    """CONTEXT_DNA_CONSENSUS_COUNTER_PROBE=on activates the gate without
    the CLI flag — verifies the env-var override path works under --json."""
    monkeypatch.setenv("CONTEXT_DNA_CONSENSUS_COUNTER_PROBE", "on")
    result = _stub_result(counter_probe_active=True, sycophantic=False)
    cli_result = _invoke_consensus(["--json", "test"], result=result)
    payload = json.loads(cli_result.stdout)
    assert payload["counter_probe_active"] is True


# ── Stdout is JSON-only (no prose leakage) ──────────────────────────


def test_json_stdout_contains_only_json():
    """Stdout must be a single JSON object — no banner, no prose preamble.

    Critical for machine consumers: json.loads(captured_stdout) must succeed
    without any pre/post-processing.
    """
    result = _stub_result()
    cli_result = _invoke_consensus(["--json", "test"], result=result)
    stripped = cli_result.stdout.strip()
    # Single JSON object: starts with '{', ends with '}'.
    assert stripped.startswith("{")
    assert stripped.endswith("}")
    # Single line (json.dumps without indent).
    assert stripped.count("\n") == 0
    # Round-trip cleanly.
    payload = json.loads(stripped)
    assert payload["claim"] == "test"


def test_json_diversity_warning_routes_to_stderr_not_stdout():
    """Diversity canary warnings must NOT leak into the JSON stdout stream."""
    result = _stub_result(
        diversity_yellow=True,
        diversity_reasons=["model-collapse: both surgeons used deepseek-chat"],
    )
    cli_result = _invoke_consensus(["--json", "test"], result=result)
    # Stdout still parses as JSON despite the yellow signal.
    payload = json.loads(cli_result.stdout)
    assert payload["diversity_yellow"] is True
    assert payload["diversity_reasons"] == [
        "model-collapse: both surgeons used deepseek-chat"
    ]
    # The warning text appears in stderr, not stdout.
    assert "Diversity canary" not in cli_result.stdout
    assert "Diversity canary" in cli_result.stderr


# ── ZSF: defensive serialization ────────────────────────────────────


def test_json_zsf_serialization_failure_yields_error_envelope(
    monkeypatch: pytest.MonkeyPatch,
):
    """If json.dumps fails (e.g. exotic object snuck into the payload),
    the CLI still emits a well-formed JSON envelope with an ``error`` key —
    it never crashes and never leaks prose."""
    import sys
    cli_main = sys.modules["three_surgeons.cli.main"]

    def _broken_serializer(_result, *, claim):
        # Return a non-JSON-serializable payload to force json.dumps to fail.
        return {"claim": claim, "bad": object()}

    monkeypatch.setattr(cli_main, "_consensus_result_to_json", _broken_serializer)
    result = _stub_result()
    cli_result = _invoke_consensus(["--json", "test"], result=result)
    # Even on failure, stdout is valid JSON.
    payload = json.loads(cli_result.stdout)
    assert "error" in payload
    assert "json_serialization_failed" in payload["error"]
