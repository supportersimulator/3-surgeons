"""Tests for cardiologist review, A/B validation, and collaboration commands."""
from __future__ import annotations

import json
from unittest.mock import MagicMock, PropertyMock

import pytest

from three_surgeons.core.cardio import (
    CardioReviewResult,
    CollaborationResult,
    ValidationResult,
    ab_collaborate,
    ab_validate,
    cardio_review,
    _parse_test_design,
    _parse_neuro_review,
)


# ── Dataclasses ──────────────────────────────────────────────────────


class TestCardioReviewResult:
    def test_fields(self):
        cr = CardioReviewResult(
            topic="auth",
            cardiologist_findings="findings",
            neurologist_blind_spots="blind spots",
            synthesis="synthesis",
        )
        assert cr.topic == "auth"
        assert cr.dissent is None
        assert cr.git_context_used is False
        assert cr.recommendations == []


class TestValidationResult:
    def test_fields(self):
        vr = ValidationResult(description="test change")
        assert vr.description == "test change"
        assert vr.gains_gate_passed is None
        assert vr.verdict == "FLAG"

    def test_surgeon_votes_default(self):
        vr = ValidationResult(description="x")
        assert vr.surgeon_votes == {}


class TestCollaborationResult:
    def test_fields(self):
        cr = CollaborationResult(claim="claim")
        assert cr.claim == "claim"
        assert cr.test_design is None
        assert cr.consensus_status == "needs_revision"
        assert cr.blocking_concerns == []


# ── cardio_review ────────────────────────────────────────────────────


class TestCardioReview:
    def _make_team(self, synthesis="Good synthesis with recommendations:\n- Do X\n- Do Y"):
        team = MagicMock()
        result = MagicMock()
        result.cardiologist_report = "Cardio findings"
        result.neurologist_report = "Neuro findings"
        result.synthesis = synthesis
        team.cross_examine.return_value = result
        return team

    def test_basic_review(self):
        team = self._make_team()
        result = cardio_review("auth security", team)
        assert isinstance(result, CardioReviewResult)
        assert result.topic == "auth security"
        assert result.cardiologist_findings == "Cardio findings"

    def test_with_git_context(self):
        team = self._make_team()
        result = cardio_review("topic", team, git_context="commit abc123")
        assert result.git_context_used is True

    def test_without_git_context(self):
        team = self._make_team()
        result = cardio_review("topic", team)
        assert result.git_context_used is False

    def test_dissent_detected(self):
        team = self._make_team(synthesis="However, the cardiologist disagrees with this approach")
        result = cardio_review("topic", team)
        assert result.dissent is not None

    def test_no_dissent(self):
        team = self._make_team(synthesis="All surgeons agree on the approach")
        result = cardio_review("topic", team)
        assert result.dissent is None

    def test_recommendations_extracted(self):
        team = self._make_team(synthesis="Recommendations:\n- Fix auth\n- Update tests\n* Add logging")
        result = cardio_review("topic", team)
        assert len(result.recommendations) == 3

    def test_with_evidence_store(self):
        team = self._make_team()
        evidence = MagicMock()
        evidence.get_evidence_snapshot.return_value = {"evidence_text": "some evidence"}
        result = cardio_review("topic", team, evidence_store=evidence)
        assert isinstance(result, CardioReviewResult)

    def test_evidence_store_error(self):
        team = self._make_team()
        evidence = MagicMock()
        evidence.get_evidence_snapshot.side_effect = RuntimeError("DB error")
        result = cardio_review("topic", team, evidence_store=evidence)
        assert isinstance(result, CardioReviewResult)


# ── cardio_review with file_paths ────────────────────────────────────


class TestCardioReviewWithFiles:
    """cardio_review with file_paths parameter."""

    def _make_team(self, synthesis="synthesis"):
        team = MagicMock()
        result = MagicMock()
        result.cardiologist_report = "findings"
        result.neurologist_report = "blind spots"
        result.synthesis = synthesis
        team.cross_examine.return_value = result
        return team

    def test_cardio_review_includes_file_content(self, tmp_path):
        test_file = tmp_path / "handler.py"
        test_file.write_text("def handle_request(req):\n    return 200\n")

        team = self._make_team()
        cardio_review("test topic", team, file_paths=[str(test_file)])

        call_args = team.cross_examine.call_args
        enriched = call_args[0][0] if call_args[0] else call_args.kwargs.get("topic", "")
        assert "handle_request" in enriched

    def test_missing_file_skipped(self):
        team = self._make_team()
        result = cardio_review("test topic", team, file_paths=["/nonexistent/file.py"])
        assert result.topic == "test topic"

    def test_no_file_paths_backward_compatible(self):
        team = self._make_team()
        result = cardio_review("test topic", team)
        assert result.topic == "test topic"


# ── ab_validate ──────────────────────────────────────────────────────


class TestAbValidate:
    def _make_team_consensus(self, cardio_conf=0.9, neuro_conf=0.9,
                              cardio_assess="agree", neuro_assess="agree"):
        team = MagicMock()
        consensus_result = MagicMock()
        consensus_result.cardiologist_confidence = cardio_conf
        consensus_result.cardiologist_assessment = cardio_assess
        consensus_result.neurologist_confidence = neuro_conf
        consensus_result.neurologist_assessment = neuro_assess
        team.consensus.return_value = consensus_result
        return team

    def test_all_keep(self):
        team = self._make_team_consensus()
        result = ab_validate("fix auth bug", team)
        assert result.verdict == "KEEP"

    def test_gains_gate_fails(self):
        team = MagicMock()
        gate = MagicMock()
        gate_result = MagicMock()
        gate_result.passed = False
        gate_result.summary = "Evidence store down"
        gate.run.return_value = gate_result
        result = ab_validate("change", team, gains_gate=gate)
        assert result.verdict == "REVERT"
        assert result.gains_gate_passed is False

    def test_gains_gate_passes(self):
        team = self._make_team_consensus()
        gate = MagicMock()
        gate_result = MagicMock()
        gate_result.passed = True
        gate.run.return_value = gate_result
        result = ab_validate("change", team, gains_gate=gate)
        assert result.gains_gate_passed is True

    def test_revert_on_disagreement(self):
        team = self._make_team_consensus(
            cardio_conf=0.3, cardio_assess="disagree",
            neuro_conf=0.9, neuro_assess="agree"
        )
        result = ab_validate("risky change", team)
        assert result.verdict == "REVERT"

    def test_flag_on_mixed(self):
        team = self._make_team_consensus(
            cardio_conf=0.5, cardio_assess="agree",
            neuro_conf=0.5, neuro_assess="agree"
        )
        result = ab_validate("uncertain change", team)
        assert result.verdict == "FLAG"

    def test_consensus_error(self):
        team = MagicMock()
        team.consensus.side_effect = RuntimeError("LLM down")
        result = ab_validate("change", team)
        assert result.verdict == "FLAG"

    def test_gains_gate_error(self):
        team = MagicMock()
        gate = MagicMock()
        gate.run.side_effect = RuntimeError("Gate broken")
        result = ab_validate("change", team, gains_gate=gate)
        assert result.verdict == "REVERT"
        assert result.gains_gate_passed is False


# ── ab_collaborate ───────────────────────────────────────────────────


class TestAbCollaborate:
    def _make_team(self, cardio_ok=True, neuro_ok=True,
                    neuro_feasibility=3, neuro_risk=1, neuro_approve=True):
        team = MagicMock()
        # Cardiologist design response
        cardio_resp = MagicMock()
        cardio_resp.ok = cardio_ok
        cardio_resp.content = json.dumps({
            "hypothesis": "X improves Y",
            "param": "cache_ttl",
            "control": "300",
            "variant": "600",
            "success_metrics": ["latency"],
            "risks": ["staleness"],
        })
        team._cardiologist = MagicMock()
        team._cardiologist.query.return_value = cardio_resp

        # Neurologist review response
        neuro_resp = MagicMock()
        neuro_resp.ok = neuro_ok
        neuro_resp.content = json.dumps({
            "measurement_feasibility": neuro_feasibility,
            "risk_level": neuro_risk,
            "approve": neuro_approve,
            "concerns": [],
        })
        team._neurologist = MagicMock()
        team._neurologist.query.return_value = neuro_resp
        return team

    def test_approved_collaboration(self):
        team = self._make_team()
        ab_engine = MagicMock()
        result = ab_collaborate("cache improves latency", team, ab_engine)
        assert result.consensus_status == "approved"
        ab_engine.propose.assert_called_once()

    def test_rejected_low_feasibility(self):
        team = self._make_team(neuro_feasibility=1)
        ab_engine = MagicMock()
        result = ab_collaborate("claim", team, ab_engine)
        assert result.consensus_status == "rejected"
        assert any("feasibility" in c.lower() for c in result.blocking_concerns)

    def test_needs_revision_high_risk(self):
        team = self._make_team(neuro_risk=3)
        ab_engine = MagicMock()
        result = ab_collaborate("claim", team, ab_engine)
        assert result.consensus_status == "needs_revision"

    def test_cardiologist_failure(self):
        team = self._make_team(cardio_ok=False)
        team._cardiologist.query.return_value.content = "Error: timeout"
        ab_engine = MagicMock()
        result = ab_collaborate("claim", team, ab_engine)
        assert result.consensus_status == "rejected"

    def test_cardiologist_exception(self):
        team = MagicMock()
        team._cardiologist = MagicMock()
        team._cardiologist.query.side_effect = RuntimeError("down")
        ab_engine = MagicMock()
        result = ab_collaborate("claim", team, ab_engine)
        assert result.consensus_status == "rejected"

    def test_forbidden_parameter(self):
        team = self._make_team()
        ab_engine = MagicMock()
        ab_engine.propose.side_effect = ValueError("Forbidden param: safety_checks")
        result = ab_collaborate("claim", team, ab_engine)
        assert result.consensus_status == "rejected"
        assert any("forbidden" in c.lower() for c in result.blocking_concerns)


# ── Parse helpers ────────────────────────────────────────────────────


class TestParseTestDesign:
    def test_valid_json(self):
        raw = json.dumps({"hypothesis": "X", "param": "p", "control": "a", "variant": "b"})
        result = _parse_test_design(raw)
        assert result["hypothesis"] == "X"

    def test_invalid_json(self):
        result = _parse_test_design("not json")
        assert result["param"] == "unknown"

    def test_json_with_text(self):
        raw = 'Here is the design: {"hypothesis": "Y", "param": "q"} end'
        result = _parse_test_design(raw)
        assert result["hypothesis"] == "Y"


class TestParseNeuroReview:
    def test_valid_json(self):
        raw = json.dumps({
            "measurement_feasibility": 3,
            "risk_level": 1,
            "approve": True,
            "concerns": [],
        })
        result = _parse_neuro_review(raw)
        assert result["approve"] is True
        assert result["measurement_feasibility"] == 3

    def test_invalid_json(self):
        result = _parse_neuro_review("not json")
        assert result["approve"] is False
        assert "Could not parse" in result["concerns"][0]

    def test_defaults_on_missing_fields(self):
        raw = json.dumps({})
        result = _parse_neuro_review(raw)
        assert result["measurement_feasibility"] == 1
        assert result["risk_level"] == 2
