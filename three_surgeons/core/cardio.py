"""Cardiologist review, A/B validation, and A/B collaboration commands.

cardio_review: Full cross-examination with optional git context.
ab_validate: Quick 3-surgeon fix validation with gains gate check.
ab_collaborate: 3-surgeon consensus A/B test design with feasibility review.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Dict, List, Optional

from three_surgeons.core.cross_exam import _read_file_context

if TYPE_CHECKING:
    from three_surgeons.adapters._protocol import SurgeryAdapter


@dataclass
class CardioReviewResult:
    """Outcome of a cardiologist review cross-examination."""

    topic: str
    cardiologist_findings: str
    neurologist_blind_spots: str
    synthesis: str
    dissent: Optional[str] = None
    git_context_used: bool = False
    recommendations: List[str] = field(default_factory=list)


@dataclass
class ValidationResult:
    """Outcome of a quick A/B validation check."""

    description: str
    gains_gate_passed: Optional[bool] = None
    surgeon_votes: Dict[str, str] = field(default_factory=dict)
    verdict: str = "FLAG"
    reasoning: str = ""


@dataclass
class CollaborationResult:
    """Outcome of a 3-surgeon A/B test collaboration."""

    claim: str
    test_design: Optional[Dict] = None
    consensus_status: str = "needs_revision"  # approved | needs_revision | rejected
    surgeon_feedback: Dict[str, str] = field(default_factory=dict)
    blocking_concerns: List[str] = field(default_factory=list)


def cardio_review(
    topic: str,
    surgery_team: Any,
    evidence_store: Any = None,
    git_context: Optional[str] = None,
    file_paths: Optional[List[str]] = None,
    adapter: Optional["SurgeryAdapter"] = None,
) -> CardioReviewResult:
    """Run a cardiologist cross-examination review.

    Optionally includes git history context and evidence store data.
    Uses the surgery team's cross_examine method for the core analysis.
    """
    # Build enriched topic with context
    enriched_topic = topic
    if git_context:
        enriched_topic += f"\n\nRecent git changes:\n{git_context}"
    if evidence_store:
        try:
            snapshot = evidence_store.get_evidence_snapshot(topic, limit=10)
            evidence_text = snapshot.get("evidence_text", "")
            if evidence_text:
                enriched_topic += f"\n\nEvidence context:\n{evidence_text}"
        except Exception:
            pass

    file_context = _read_file_context(file_paths)
    if file_context:
        enriched_topic += f"\n\n{file_context}"

    # Run cross-examination
    result = surgery_team.cross_examine(enriched_topic)

    # Extract components
    cardio_findings = result.cardiologist_report or "(unavailable)"
    neuro_findings = result.neurologist_report or "(unavailable)"
    synthesis = result.synthesis or "(no synthesis available)"

    # Detect dissent: check if reports contain disagreement signals
    dissent = None
    if result.synthesis:
        dissent_keywords = ["disagree", "however", "contrary", "but", "conflict", "dispute"]
        lower_synth = result.synthesis.lower()
        if any(kw in lower_synth for kw in dissent_keywords):
            dissent = "Potential disagreement detected in synthesis"

    # Extract recommendations from synthesis
    recommendations: List[str] = []
    if synthesis and synthesis != "(no synthesis available)":
        for line in synthesis.split("\n"):
            line = line.strip()
            if line.startswith("-") or line.startswith("*") or line.startswith("•"):
                recommendations.append(line.lstrip("-*• ").strip())

    review_result = CardioReviewResult(
        topic=topic,
        cardiologist_findings=cardio_findings,
        neurologist_blind_spots=neuro_findings,
        synthesis=synthesis,
        dissent=dissent,
        git_context_used=git_context is not None,
        recommendations=recommendations[:10],
    )

    if adapter is not None:
        try:
            adapter.on_cross_exam_logged(topic, {"type": "cardio_review"})
        except Exception:
            pass

    return review_result


def ab_validate(
    description: str,
    surgery_team: Any,
    gains_gate: Any = None,
    adapter: Optional["SurgeryAdapter"] = None,
) -> ValidationResult:
    """Quick 3-surgeon fix validation.

    Runs gains gate first (if provided), then consensus check.
    Maps confidence scores to keep/flag/revert votes.
    """
    result = ValidationResult(description=description)

    # Step 1: Gains gate check
    if gains_gate is not None:
        try:
            gate_result = gains_gate.run()
            result.gains_gate_passed = gate_result.passed
            if not gate_result.passed:
                result.verdict = "REVERT"
                result.reasoning = f"Gains gate failed: {gate_result.summary}"
                return result
        except Exception as exc:
            result.gains_gate_passed = False
            result.verdict = "REVERT"
            result.reasoning = f"Gains gate error: {exc}"
            return result

    # Step 2: Consensus check
    try:
        consensus = surgery_team.consensus(f"This change should be kept: {description}")

        # Map confidence + assessment to votes
        votes = {}
        for name, conf, assessment in [
            ("cardiologist", consensus.cardiologist_confidence, consensus.cardiologist_assessment),
            ("neurologist", consensus.neurologist_confidence, consensus.neurologist_assessment),
        ]:
            if assessment == "agree" and conf > 0.7:
                votes[name] = "keep"
            elif assessment == "disagree" or conf < 0.4:
                votes[name] = "revert"
            else:
                votes[name] = "flag"

        result.surgeon_votes = votes

        # Determine overall verdict
        vote_values = list(votes.values())
        if all(v == "keep" for v in vote_values):
            result.verdict = "KEEP"
            result.reasoning = "All surgeons agree: keep the change"
        elif any(v == "revert" for v in vote_values):
            result.verdict = "REVERT"
            reverters = [n for n, v in votes.items() if v == "revert"]
            result.reasoning = f"Revert recommended by: {', '.join(reverters)}"
        else:
            result.verdict = "FLAG"
            result.reasoning = "Mixed signals — manual review recommended"

    except Exception as exc:
        result.verdict = "FLAG"
        result.reasoning = f"Consensus check error: {exc}"

    if adapter is not None:
        try:
            adapter.on_cross_exam_logged(description, {"type": "ab_validate", "verdict": result.verdict})
        except Exception:
            pass

    return result


def ab_collaborate(
    claim: str,
    surgery_team: Any,
    ab_engine: Any,
    evidence_store: Any = None,
) -> CollaborationResult:
    """3-surgeon collaborative A/B test design.

    Phase 1: Cardiologist designs the test.
    Phase 2: Neurologist reviews feasibility.
    Phase 3: Consensus determination and optional registration.
    """
    result = CollaborationResult(claim=claim)

    # Get evidence context if available
    evidence_context = ""
    if evidence_store:
        try:
            snapshot = evidence_store.get_evidence_snapshot(claim, limit=10)
            evidence_context = snapshot.get("evidence_text", "")
        except Exception:
            pass

    # Phase 1: Cardiologist designs test
    design_system = (
        "You are designing an A/B test for a claim. Output JSON with: "
        "hypothesis (string), param (what to test), control (current value), "
        "variant (proposed change), success_metrics (list of strings), "
        "risks (list of strings), measurement_feasibility (0-3 integer), "
        "risk_level (0-3 integer)."
    )
    design_prompt = f"Design an A/B test for: {claim}"
    if evidence_context:
        design_prompt += f"\n\nExisting evidence:\n{evidence_context}"

    try:
        cardio_resp = surgery_team._cardiologist.query(
            system=design_system, prompt=design_prompt, max_tokens=2048, temperature=0.5
        )
        if cardio_resp.ok:
            result.surgeon_feedback["cardiologist"] = cardio_resp.content
        else:
            result.surgeon_feedback["cardiologist"] = f"Error: {cardio_resp.content}"
            result.consensus_status = "rejected"
            result.blocking_concerns.append("Cardiologist failed to respond")
            return result
    except Exception as exc:
        result.consensus_status = "rejected"
        result.blocking_concerns.append(f"Cardiologist error: {exc}")
        return result

    # Parse cardiologist design
    test_design = _parse_test_design(cardio_resp.content)
    result.test_design = test_design

    # Phase 2: Neurologist reviews feasibility
    review_system = (
        "You are reviewing an A/B test design for feasibility. Output JSON with: "
        "measurement_feasibility (0-3 integer, 3=highly feasible), "
        "risk_level (0-3 integer, 0=no risk), approve (boolean), "
        "concerns (list of strings)."
    )
    review_prompt = f"Review this A/B test design:\n{json.dumps(test_design, indent=2)}"

    try:
        neuro_resp = surgery_team._neurologist.query(
            system=review_system, prompt=review_prompt, max_tokens=1024, temperature=0.3
        )
        if neuro_resp.ok:
            result.surgeon_feedback["neurologist"] = neuro_resp.content
        else:
            result.surgeon_feedback["neurologist"] = f"Error: {neuro_resp.content}"
    except Exception as exc:
        result.surgeon_feedback["neurologist"] = f"Error: {exc}"

    # Parse neurologist review
    neuro_review = _parse_neuro_review(result.surgeon_feedback.get("neurologist", ""))

    # Phase 3: Consensus determination
    meas_feasibility = neuro_review.get("measurement_feasibility", 1)
    risk_level = neuro_review.get("risk_level", 2)
    approve = neuro_review.get("approve", False)

    if meas_feasibility >= 2 and risk_level <= 2 and approve:
        result.consensus_status = "approved"
        # Register the test
        try:
            param = test_design.get("param", claim[:50])
            control = test_design.get("control", "current")
            variant = test_design.get("variant", "proposed")
            hypothesis = test_design.get("hypothesis", claim)
            ab_engine.propose(
                param=param,
                variant_a=control,
                variant_b=variant,
                hypothesis=hypothesis,
            )
        except ValueError as exc:
            result.consensus_status = "rejected"
            result.blocking_concerns.append(f"Forbidden parameter: {exc}")
    elif meas_feasibility < 2:
        result.consensus_status = "rejected"
        result.blocking_concerns.append(f"Low measurement feasibility: {meas_feasibility}/3")
    elif risk_level > 2:
        result.consensus_status = "needs_revision"
        result.blocking_concerns.append(f"High risk level: {risk_level}/3")
    else:
        result.consensus_status = "needs_revision"
        result.blocking_concerns.extend(neuro_review.get("concerns", []))

    return result


def _parse_test_design(raw: str) -> Dict:
    """Parse A/B test design JSON from cardiologist response."""
    try:
        text = raw.strip()
        start = text.find("{")
        end = text.rfind("}")
        if start >= 0 and end > start:
            text = text[start : end + 1]
        return json.loads(text)
    except (json.JSONDecodeError, TypeError, ValueError):
        return {"hypothesis": raw[:200], "param": "unknown", "control": "current", "variant": "proposed"}


def _parse_neuro_review(raw: str) -> Dict:
    """Parse neurologist feasibility review JSON."""
    try:
        text = raw.strip()
        start = text.find("{")
        end = text.rfind("}")
        if start >= 0 and end > start:
            text = text[start : end + 1]
        data = json.loads(text)
        return {
            "measurement_feasibility": int(data.get("measurement_feasibility", 1)),
            "risk_level": int(data.get("risk_level", 2)),
            "approve": bool(data.get("approve", False)),
            "concerns": list(data.get("concerns", [])),
        }
    except (json.JSONDecodeError, TypeError, ValueError):
        return {"measurement_feasibility": 1, "risk_level": 2, "approve": False, "concerns": ["Could not parse review"]}
