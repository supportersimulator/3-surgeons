"""Cross-examination engine for multi-model consensus evaluation.

Orchestrates the Cardiologist and Neurologist through three operations:
consult, cross_examine (4-phase with open exploration), and consensus.

Philosophy: "The value is in the disagreements, not the agreements."
Corrigibility: "What are we ALL blind to?" surfaces unknown unknowns.
"""
from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import List, Optional, Protocol

from three_surgeons.adapters._protocol import SurgeryAdapter
from three_surgeons.adapters._standalone import StandaloneAdapter
from three_surgeons.core.confabulation_detector import detect_confabulation
from three_surgeons.core.evidence import EvidenceStore
from three_surgeons.core.file_access import AccessOutcome, FileAccessPolicy, read_files_with_budget, wrap_file_content
from three_surgeons.core.sessions import LiveSession
from three_surgeons.core.state import StateBackend

logger = logging.getLogger(__name__)


def _get_file_policy() -> FileAccessPolicy:
    """Build file access policy from env or cwd. No caching — env may change."""
    env_dirs = os.environ.get("THREE_SURGEONS_BASE_DIRS", "")
    if env_dirs:
        base_dirs = [Path(d.strip()) for d in env_dirs.split(":") if d.strip()]
    else:
        base_dirs = [Path(os.getcwd())]
    return FileAccessPolicy(base_dirs=base_dirs)


def _read_file_context(file_paths: Optional[List[str]]) -> str:
    """Read validated, chunked files as context for LLM prompts."""
    if not file_paths:
        return ""
    policy = _get_file_policy()
    file_contents = read_files_with_budget(file_paths, policy)
    if not file_contents:
        return ""
    parts: List[str] = ["Relevant source files:"]
    for path, content in file_contents.items():
        parts.append(wrap_file_content(path, content))
    return "\n".join(parts)


class LLMProviderLike(Protocol):
    """Protocol for anything that can answer LLM queries (real or mock)."""

    def query(
        self,
        system: str,
        prompt: str,
        max_tokens: int = ...,
        temperature: float = ...,
        timeout_s: float = ...,
    ) -> "LLMResponseLike": ...


class LLMResponseLike(Protocol):
    """Minimal response shape we depend on."""

    ok: bool
    content: str
    latency_ms: int
    model: str
    cost_usd: float


# ── Review Mode ──────────────────────────────────────────────────────


class ReviewMode(Enum):
    """Controls how many cross-exam iterations the review loop performs."""

    SINGLE = "single"
    ITERATIVE = "iterative"
    CONTINUOUS = "continuous"

    @property
    def max_iterations(self) -> int:
        """Maximum number of review iterations for this mode."""
        return {"single": 1, "iterative": 3, "continuous": 5}[self.value]

    @classmethod
    def from_string(cls, value: str) -> "ReviewMode":
        """Parse a string to ReviewMode, case-insensitive. Defaults to SINGLE."""
        try:
            return cls(value.lower())
        except ValueError:
            return cls.SINGLE


# ── Result Dataclasses ───────────────────────────────────────────────


@dataclass
class CrossExamResult:
    """Result from a consult or cross_examine operation."""

    topic: str
    neurologist_report: Optional[str] = None
    cardiologist_report: Optional[str] = None
    neurologist_exploration: Optional[str] = None
    cardiologist_exploration: Optional[str] = None
    synthesis: Optional[str] = None
    total_cost: float = 0.0
    total_latency_ms: float = 0.0
    warnings: list = field(default_factory=list)
    iteration_count: int = 1
    mode_used: str = "single"
    escalation_needed: bool = False
    unresolved_summary: Optional[str] = None
    confabulation_flags: dict = field(default_factory=dict)

    @property
    def surgeon_count(self) -> int:
        """Number of surgeons that contributed (excluding Atlas)."""
        count = 0
        if self.cardiologist_report:
            count += 1
        if self.neurologist_report:
            count += 1
        return count


@dataclass
class ConsensusResult:
    """Result from a consensus (confidence-weighted vote) operation."""

    claim: str
    neurologist_confidence: float = 0.0
    neurologist_assessment: str = "unavailable"
    cardiologist_confidence: float = 0.0
    cardiologist_assessment: str = "unavailable"
    weighted_score: float = 0.0
    total_cost: float = 0.0
    confabulation_flags: dict = field(default_factory=dict)


# ── Prompt Templates ─────────────────────────────────────────────────

_CONSULT_SYSTEM = (
    "You are a {role} surgeon in a multi-model evaluation team. "
    "Analyze the topic independently. Be concise and evidence-based."
)

_CROSS_EXAM_REVIEW_SYSTEM = (
    "You are a {role} surgeon reviewing another surgeon's analysis. "
    "Identify strengths, weaknesses, blind spots, and disagreements. "
    "Be specific and evidence-based. Highlight what the other surgeon "
    "missed or got wrong."
)

_CROSS_EXAM_REVIEW_PROMPT = (
    "Original topic: {topic}\n\n"
    "The other surgeon's analysis:\n{other_analysis}\n\n"
    "Provide your cross-examination review. Focus on disagreements and "
    "what was missed."
)

_EXPLORATION_SYSTEM = (
    "You are a surgeon who has reviewed two colleagues' "
    "initial analyses and cross-examinations (provided below). Your role now "
    "is OPEN EXPLORATION -- go beyond what was already covered.\n\n"
    "Focus on:\n"
    "- What are we ALL blind to? What assumptions remain unchallenged?\n"
    "- What adjacent systems, failure modes, or interactions were not considered?\n"
    "- What would a domain expert immediately ask that we haven't?\n"
    "- Are there academic, industry, or historical precedents we're ignoring?\n"
    "- What are the worst-case scenarios nobody mentioned?\n\n"
    "Do NOT repeat prior analysis. Surface only NEW insights."
)

_EXPLORATION_PROMPT = (
    "TOPIC: {topic}\n\n"
    "=== TEAM ANALYSIS SO FAR ===\n"
    "--- Cardiologist ---\n{cardio_report}\n\n"
    "--- Neurologist ---\n{neuro_report}\n\n"
    "Now: What are we blind to? What haven't we considered? "
    "Surface unknown unknowns -- the things we don't know we don't know."
)

_SYNTHESIS_SYSTEM = (
    "You are synthesizing two independent surgical analyses. "
    "Focus on DISAGREEMENTS -- where the surgeons diverge is the most "
    "valuable signal. Also note agreements for completeness."
)

_SYNTHESIS_PROMPT = (
    "Topic: {topic}\n\n"
    "--- Cardiologist ---\n{cardio_report}\n\n"
    "--- Neurologist ---\n{neuro_report}\n\n"
    "{exploration_section}"
    "Synthesize. Emphasize disagreements."
)

_CONSENSUS_SYSTEM = (
    "You are evaluating a claim as part of a multi-model consensus. "
    'Respond with ONLY valid JSON: {{"confidence": 0.0-1.0, '
    '"assessment": "agree"|"disagree"|"uncertain", '
    '"reasoning": "brief explanation"}}'
)

_CONSENSUS_PROMPT = 'Evaluate this claim: "{claim}"'


# ── SurgeryTeam ──────────────────────────────────────────────────────


class SurgeryTeam:
    """Orchestrates multi-model evaluation across Cardiologist and Neurologist.

    Three operations:
    - consult: quick parallel query, raw analyses
    - cross_examine: deep 4-phase evaluation with cross-review, open
      exploration (corrigibility), and synthesis
    - consensus: confidence-weighted vote on a specific claim
    """

    def __init__(
        self,
        cardiologist: LLMProviderLike,
        neurologist: LLMProviderLike,
        evidence: EvidenceStore,
        state: StateBackend,
        adapter: SurgeryAdapter | None = None,
    ) -> None:
        self._cardiologist = cardiologist
        self._neurologist = neurologist
        self._evidence = evidence
        self._state = state
        self._adapter = adapter or StandaloneAdapter()

    # ── consult ──────────────────────────────────────────────────────

    def consult(self, topic: str, file_paths: Optional[List[str]] = None) -> CrossExamResult:
        """Quick parallel query to both surgeons. Returns raw analyses.

        No cross-examination or synthesis -- just independent opinions.
        Logs result in evidence store.
        """
        file_context = _read_file_context(file_paths)
        if file_context:
            topic = f"{topic}\n\n{file_context}"
        result = CrossExamResult(topic=topic)

        # Query cardiologist
        cardio_resp = self._safe_query(
            self._cardiologist,
            system=_CONSULT_SYSTEM.format(role="cardiologist"),
            prompt=topic,
        )
        if cardio_resp is not None:
            result.cardiologist_report = cardio_resp.content
            result.total_cost += cardio_resp.cost_usd
            result.total_latency_ms += cardio_resp.latency_ms
            self._track_cost("cardiologist", cardio_resp.cost_usd, "consult")

        # Query neurologist
        neuro_resp = self._safe_query(
            self._neurologist,
            system=_CONSULT_SYSTEM.format(role="neurologist"),
            prompt=topic,
        )
        if neuro_resp is not None:
            result.neurologist_report = neuro_resp.content
            result.total_cost += neuro_resp.cost_usd
            result.total_latency_ms += neuro_resp.latency_ms
            self._track_cost("neurologist", neuro_resp.cost_usd, "consult")

        # Degradation warnings
        if cardio_resp is None:
            result.warnings.append("Cardiologist (remote LLM) unreachable — consulting with neurologist only.")
        if neuro_resp is None:
            result.warnings.append("Neurologist (local LLM) unreachable — consulting with cardiologist only.")

        # Confabulation regression check (RACE M2)
        cardio_flag = self._check_confabulation(
            "cardiologist", topic, result.cardiologist_report, result.warnings
        )
        neuro_flag = self._check_confabulation(
            "neurologist", topic, result.neurologist_report, result.warnings
        )
        if cardio_flag:
            result.confabulation_flags["cardiologist"] = cardio_flag
        if neuro_flag:
            result.confabulation_flags["neurologist"] = neuro_flag

        # Log to evidence store
        self._log_cross_exam(result)

        return result

    # ── cross_examine ────────────────────────────────────────────────

    def cross_examine(
        self, topic: str, depth: str = "full", file_paths: Optional[List[str]] = None
    ) -> CrossExamResult:
        """Deep multi-phase evaluation.

        Phase 1: Both surgeons analyze independently.
        Phase 2: Each surgeon reviews the other's analysis.
        Phase 3: Open exploration -- surface unknown unknowns (corrigibility).
        Phase 4: Synthesize all findings, highlight disagreements.

        Handles model failures gracefully -- one surgeon failing does not
        crash the entire operation.
        """
        file_context = _read_file_context(file_paths)
        if file_context:
            topic = f"{topic}\n\n{file_context}"
        result = CrossExamResult(topic=topic)

        # ── Phase 1: Independent analysis ────────────────────────────
        cardio_initial = self._safe_query(
            self._cardiologist,
            system=_CONSULT_SYSTEM.format(role="cardiologist"),
            prompt=topic,
        )
        neuro_initial = self._safe_query(
            self._neurologist,
            system=_CONSULT_SYSTEM.format(role="neurologist"),
            prompt=topic,
        )

        cardio_text = cardio_initial.content if cardio_initial else None
        neuro_text = neuro_initial.content if neuro_initial else None

        # Accumulate cost/latency from phase 1
        if cardio_initial:
            result.total_cost += cardio_initial.cost_usd
            result.total_latency_ms += cardio_initial.latency_ms
            self._track_cost("cardiologist", cardio_initial.cost_usd, "cross_examine_p1")
        if neuro_initial:
            result.total_cost += neuro_initial.cost_usd
            result.total_latency_ms += neuro_initial.latency_ms
            self._track_cost("neurologist", neuro_initial.cost_usd, "cross_examine_p1")

        # ── Degradation warnings ──────────────────────────────────────
        if cardio_initial is None:
            msg = "Cardiologist (remote LLM) unreachable — proceeding without. Run '3s probe' for details."
            result.warnings.append(msg)
            logger.warning(msg)
        if neuro_initial is None:
            msg = "Neurologist (local LLM) unreachable — proceeding without. Run '3s probe' for details."
            result.warnings.append(msg)
            logger.warning(msg)
        if cardio_initial is None and neuro_initial is None:
            msg = "Both surgeons unreachable — cross-examination has no external input."
            result.warnings.append(msg)
            logger.error(msg)

        # ── Phase 2: Cross-review ────────────────────────────────────
        # Each surgeon reviews the other's analysis
        cardio_review = None
        neuro_review = None

        if neuro_text:
            # Cardiologist reviews neurologist's analysis
            cardio_review = self._safe_query(
                self._cardiologist,
                system=_CROSS_EXAM_REVIEW_SYSTEM.format(role="cardiologist"),
                prompt=_CROSS_EXAM_REVIEW_PROMPT.format(
                    topic=topic, other_analysis=neuro_text
                ),
            )
            if cardio_review:
                result.total_cost += cardio_review.cost_usd
                result.total_latency_ms += cardio_review.latency_ms
                self._track_cost(
                    "cardiologist", cardio_review.cost_usd, "cross_examine_p2"
                )

        if cardio_text:
            # Neurologist reviews cardiologist's analysis
            neuro_review = self._safe_query(
                self._neurologist,
                system=_CROSS_EXAM_REVIEW_SYSTEM.format(role="neurologist"),
                prompt=_CROSS_EXAM_REVIEW_PROMPT.format(
                    topic=topic, other_analysis=cardio_text
                ),
            )
            if neuro_review:
                result.total_cost += neuro_review.cost_usd
                result.total_latency_ms += neuro_review.latency_ms
                self._track_cost(
                    "neurologist", neuro_review.cost_usd, "cross_examine_p2"
                )

        # Build final reports: initial analysis + cross-review
        result.cardiologist_report = self._build_report(
            cardio_text, cardio_review
        )
        result.neurologist_report = self._build_report(
            neuro_text, neuro_review
        )

        # ── Phase 3: Open Exploration (corrigibility) ───────────────
        # Each surgeon receives ALL prior analysis and surfaces unknown
        # unknowns. The value is in what nobody thought to examine.
        if result.cardiologist_report and result.neurologist_report:
            explore_prompt = _EXPLORATION_PROMPT.format(
                topic=topic,
                cardio_report=result.cardiologist_report,
                neuro_report=result.neurologist_report,
            )

            # Cardiologist explores
            cardio_explore = self._safe_query(
                self._cardiologist,
                system=_EXPLORATION_SYSTEM,
                prompt=explore_prompt,
            )
            if cardio_explore:
                result.cardiologist_exploration = cardio_explore.content
                result.total_cost += cardio_explore.cost_usd
                result.total_latency_ms += cardio_explore.latency_ms
                self._track_cost(
                    "cardiologist", cardio_explore.cost_usd, "cross_examine_p3"
                )

            # Neurologist explores
            neuro_explore = self._safe_query(
                self._neurologist,
                system=_EXPLORATION_SYSTEM,
                prompt=explore_prompt,
            )
            if neuro_explore:
                result.neurologist_exploration = neuro_explore.content
                result.total_cost += neuro_explore.cost_usd
                result.total_latency_ms += neuro_explore.latency_ms
                self._track_cost(
                    "neurologist", neuro_explore.cost_usd, "cross_examine_p3"
                )

        # ── Phase 4: Synthesis ───────────────────────────────────────
        # Use cardiologist for synthesis (external model, broader perspective)
        if result.cardiologist_report and result.neurologist_report:
            # Include exploration findings in synthesis when available
            exploration_parts = []
            if result.cardiologist_exploration:
                exploration_parts.append(
                    f"--- Cardiologist Exploration ---\n"
                    f"{result.cardiologist_exploration}"
                )
            if result.neurologist_exploration:
                exploration_parts.append(
                    f"--- Neurologist Exploration ---\n"
                    f"{result.neurologist_exploration}"
                )
            exploration_section = (
                "=== OPEN EXPLORATION (unknown unknowns) ===\n"
                + "\n\n".join(exploration_parts)
                + "\n\n"
                if exploration_parts
                else ""
            )

            synth_resp = self._safe_query(
                self._cardiologist,
                system=_SYNTHESIS_SYSTEM,
                prompt=_SYNTHESIS_PROMPT.format(
                    topic=topic,
                    cardio_report=result.cardiologist_report,
                    neuro_report=result.neurologist_report,
                    exploration_section=exploration_section,
                ),
            )
            if synth_resp:
                result.synthesis = synth_resp.content
                result.total_cost += synth_resp.cost_usd
                result.total_latency_ms += synth_resp.latency_ms
                self._track_cost(
                    "cardiologist", synth_resp.cost_usd, "cross_examine_synth"
                )

        # ── Confabulation regression check (RACE M2) ──────────────────
        cardio_flag = self._check_confabulation(
            "cardiologist", topic, result.cardiologist_report, result.warnings
        )
        neuro_flag = self._check_confabulation(
            "neurologist", topic, result.neurologist_report, result.warnings
        )
        if cardio_flag:
            result.confabulation_flags["cardiologist"] = cardio_flag
        if neuro_flag:
            result.confabulation_flags["neurologist"] = neuro_flag

        # Log to evidence store
        self._log_cross_exam(result)

        return result

    # ── cross_examine_iterative ──────────────────────────────────────

    def cross_examine_iterative(
        self,
        topic: str,
        mode: ReviewMode = ReviewMode.SINGLE,
        consensus_threshold: float = 0.7,
        depth: str = "full",
        file_paths: Optional[List[str]] = None,
    ) -> CrossExamResult:
        """Iterative cross-examination that loops until consensus or max iterations.

        Args:
            topic: The topic to examine.
            mode: ReviewMode controlling max iterations (SINGLE=1, ITERATIVE=3, CONTINUOUS=5).
            consensus_threshold: Weighted score threshold to consider consensus reached.
            depth: Depth parameter passed to each cross_examine call.

        Returns:
            CrossExamResult with iteration_count, mode_used, and escalation info.
        """
        max_iters = mode.max_iterations
        accumulated_findings: list[str] = []
        final: Optional[CrossExamResult] = None
        total_cost = 0.0
        consensus_reached = False

        for i in range(1, max_iters + 1):
            # Build topic: include prior findings after first iteration
            if i == 1 or not accumulated_findings:
                iter_topic = topic
            else:
                prior = "\n\n".join(accumulated_findings)
                iter_topic = (
                    f"{topic}\n\n"
                    f"=== Prior iteration findings (iteration {i}/{max_iters}) ===\n"
                    f"{prior}"
                )

            result = self.cross_examine(iter_topic, depth=depth, file_paths=file_paths)
            total_cost += result.total_cost

            # Accumulate findings for next iteration
            parts = []
            if result.synthesis:
                parts.append(result.synthesis)
            elif result.cardiologist_report:
                parts.append(result.cardiologist_report)
            if parts:
                accumulated_findings.append(f"[Iteration {i}] " + " ".join(parts))

            final = result

            # For SINGLE mode, skip consensus check
            if mode == ReviewMode.SINGLE:
                break

            # Check consensus after each iteration
            consensus_result = self.consensus(
                "All issues from this review have been addressed"
            )
            total_cost += consensus_result.total_cost

            if consensus_result.weighted_score >= consensus_threshold:
                consensus_reached = True
                break

        # Should always have a result, but guard anyway
        if final is None:
            raise RuntimeError(
                f"cross_examine_iterative produced no result after {max_iters} iterations"
            )

        # Set iterative metadata on final result
        final.iteration_count = i  # noqa: F821 — loop variable from for-loop
        final.mode_used = mode.value
        final.total_cost = total_cost

        if not consensus_reached and mode != ReviewMode.SINGLE:
            final.escalation_needed = True
            final.unresolved_summary = (
                f"Consensus not reached after {i} iterations "
                f"(threshold={consensus_threshold}). "
                f"Accumulated {len(accumulated_findings)} iteration findings."
            )

        # Record outcome for adaptive learning
        # Use the last loop iteration's consensus score (already computed above)
        # instead of making a redundant second consensus call.
        consensus_score = (
            consensus_result.weighted_score
            if mode != ReviewMode.SINGLE
            else 0.0
        )

        self._evidence.record_review_outcome(
            topic=topic,
            mode_used=mode.value,
            iteration_count=final.iteration_count,
            consensus_reached=not final.escalation_needed,
            consensus_score=consensus_score,
            escalation_needed=final.escalation_needed,
        )

        return final

    # ── consensus ────────────────────────────────────────────────────

    def consensus(self, claim: str) -> ConsensusResult:
        """Confidence-weighted vote on a specific claim.

        Asks each surgeon to rate confidence (0-1) and assessment
        (agree/disagree/uncertain). Calculates weighted consensus score.

        Handles JSON parsing failures gracefully -- a surgeon that returns
        non-JSON gets default confidence 0.0 and assessment "unavailable".
        """
        result = ConsensusResult(claim=claim)

        # Query cardiologist (json_mode + reasoning-aware budget bump in provider)
        cardio_resp = self._safe_query(
            self._cardiologist,
            system=_CONSENSUS_SYSTEM,
            prompt=_CONSENSUS_PROMPT.format(claim=claim),
            max_tokens=512,
            temperature=0.2,
            json_mode=True,
        )
        warnings: List[str] = []
        if cardio_resp:
            result.total_cost += cardio_resp.cost_usd
            self._track_cost("cardiologist", cardio_resp.cost_usd, "consensus")
            parsed = self._parse_consensus_json(cardio_resp.content)
            result.cardiologist_confidence = parsed["confidence"]
            result.cardiologist_assessment = parsed["assessment"]
            cardio_flag = self._check_confabulation(
                "cardiologist", claim, cardio_resp.content, warnings
            )
            if cardio_flag:
                result.confabulation_flags["cardiologist"] = cardio_flag

        # Query neurologist (same budget + json_mode as cardio for parity)
        neuro_resp = self._safe_query(
            self._neurologist,
            system=_CONSENSUS_SYSTEM,
            prompt=_CONSENSUS_PROMPT.format(claim=claim),
            max_tokens=512,
            temperature=0.2,
            json_mode=True,
        )
        if neuro_resp:
            result.total_cost += neuro_resp.cost_usd
            self._track_cost("neurologist", neuro_resp.cost_usd, "consensus")
            parsed = self._parse_consensus_json(neuro_resp.content)
            result.neurologist_confidence = parsed["confidence"]
            result.neurologist_assessment = parsed["assessment"]
            neuro_flag = self._check_confabulation(
                "neurologist", claim, neuro_resp.content, warnings
            )
            if neuro_flag:
                result.confabulation_flags["neurologist"] = neuro_flag

        # Calculate weighted consensus score
        result.weighted_score = self._calculate_weighted_score(result)

        return result

    # ── Phased cross-examination (Live Surgery Transparency) ────────

    def _phased_result(
        self,
        session: LiveSession,
        phase: str,
        cardio_data: dict,
        neuro_data: dict,
        phase_summary: str = "",
        warnings: Optional[List[str]] = None,
    ) -> dict:
        """Build the standard phased result dict."""
        return {
            "session_id": session.session_id,
            "phase": phase,
            "iteration": session.current_iteration,
            "cardiologist": cardio_data,
            "neurologist": neuro_data,
            "phase_summary": phase_summary,
            "next_action": session.next_action(),
            "warnings": warnings or [],
        }

    @staticmethod
    def _surgeon_data(
        resp: Optional[LLMResponseLike],
        *,
        fallback_findings: Optional[List[str]] = None,
    ) -> dict:
        """Extract structured surgeon data from an LLM response."""
        if resp is None:
            return {
                "findings": fallback_findings or [],
                "confidence": 0.0,
                "cost_usd": 0.0,
                "latency_ms": 0,
                "status": "unavailable",
            }
        # Split content into findings (one per paragraph/line-group)
        lines = [ln.strip() for ln in resp.content.split("\n") if ln.strip()]
        return {
            "findings": lines or [resp.content],
            "confidence": 0.7,  # default; synthesize overrides with parsed value
            "cost_usd": resp.cost_usd,
            "latency_ms": resp.latency_ms,
            "status": "ok",
        }

    def phase_start(self, session: LiveSession) -> dict:
        """Phase 1: Both surgeons analyze independently.

        Queries cardiologist and neurologist with the session topic.
        Returns structured per-surgeon data. Advances session to 'start'.
        """
        if session.current_phase != "start":
            session.advance_phase("start")
        topic = session.topic
        if session.file_context:
            topic = f"{topic}\n\n{session.file_context}"

        warnings: List[str] = []

        cardio_resp = self._safe_query(
            self._cardiologist,
            system=_CONSULT_SYSTEM.format(role="cardiologist"),
            prompt=topic,
        )
        neuro_resp = self._safe_query(
            self._neurologist,
            system=_CONSULT_SYSTEM.format(role="neurologist"),
            prompt=topic,
        )

        # Both failed — error immediately
        if cardio_resp is None and neuro_resp is None:
            warnings.append("Both surgeons unreachable — cannot proceed.")
            session.warnings.extend(warnings)
            return self._phased_result(
                session, "start",
                self._surgeon_data(None), self._surgeon_data(None),
                phase_summary="Both surgeons unavailable.",
                warnings=warnings,
            )

        # Degradation warnings
        if cardio_resp is None:
            warnings.append("Cardiologist unreachable — proceeding with neurologist only.")
        if neuro_resp is None:
            warnings.append("Neurologist unreachable — proceeding with cardiologist only.")

        # Track cost
        cardio_data = self._surgeon_data(cardio_resp)
        neuro_data = self._surgeon_data(neuro_resp)
        if cardio_resp:
            session.track_cost(cardio_resp.cost_usd)
            self._track_cost("cardiologist", cardio_resp.cost_usd, "phase_start")
        if neuro_resp:
            session.track_cost(neuro_resp.cost_usd)
            self._track_cost("neurologist", neuro_resp.cost_usd, "phase_start")

        # Record findings
        session.add_finding(
            session.current_iteration, "start",
            cardiologist=cardio_data["findings"],
            neurologist=neuro_data["findings"],
        )
        session.warnings.extend(warnings)

        summary = "Independent analyses complete."
        if warnings:
            summary += f" ({len(warnings)} warning(s))"

        return self._phased_result(
            session, "start", cardio_data, neuro_data,
            phase_summary=summary, warnings=warnings,
        )

    def phase_deepen(self, session: LiveSession) -> dict:
        """Phase 2: Each surgeon cross-reviews the other's initial analysis.

        Reads the last 'start' findings from session to build cross-review prompts.
        Advances session to 'deepen'.
        """
        session.advance_phase("deepen")
        topic = session.topic
        if session.file_context:
            topic = f"{topic}\n\n{session.file_context}"

        warnings: List[str] = []

        # Get initial findings from session
        start_findings = [
            f for f in session.accumulated_findings
            if f["phase"] == "start" and f["iteration"] == session.current_iteration
        ]
        cardio_initial = ""
        neuro_initial = ""
        if start_findings:
            last = start_findings[-1]
            if last.get("cardiologist"):
                cardio_initial = "\n".join(last["cardiologist"]) if isinstance(last["cardiologist"], list) else str(last["cardiologist"])
            if last.get("neurologist"):
                neuro_initial = "\n".join(last["neurologist"]) if isinstance(last["neurologist"], list) else str(last["neurologist"])

        # Cardiologist reviews neurologist's analysis
        cardio_resp = None
        if neuro_initial:
            cardio_resp = self._safe_query(
                self._cardiologist,
                system=_CROSS_EXAM_REVIEW_SYSTEM.format(role="cardiologist"),
                prompt=_CROSS_EXAM_REVIEW_PROMPT.format(
                    topic=topic, other_analysis=neuro_initial,
                ),
            )
        else:
            warnings.append("No neurologist findings to cross-review.")

        # Neurologist reviews cardiologist's analysis
        neuro_resp = None
        if cardio_initial:
            neuro_resp = self._safe_query(
                self._neurologist,
                system=_CROSS_EXAM_REVIEW_SYSTEM.format(role="neurologist"),
                prompt=_CROSS_EXAM_REVIEW_PROMPT.format(
                    topic=topic, other_analysis=cardio_initial,
                ),
            )
        else:
            warnings.append("No cardiologist findings to cross-review.")

        if cardio_resp is None and neuro_resp is None and (cardio_initial or neuro_initial):
            warnings.append("Both surgeons failed cross-review queries.")

        cardio_data = self._surgeon_data(cardio_resp)
        neuro_data = self._surgeon_data(neuro_resp)

        if cardio_resp:
            session.track_cost(cardio_resp.cost_usd)
            self._track_cost("cardiologist", cardio_resp.cost_usd, "phase_deepen")
        if neuro_resp:
            session.track_cost(neuro_resp.cost_usd)
            self._track_cost("neurologist", neuro_resp.cost_usd, "phase_deepen")

        session.add_finding(
            session.current_iteration, "deepen",
            cardiologist=cardio_data["findings"],
            neurologist=neuro_data["findings"],
        )
        session.warnings.extend(warnings)

        return self._phased_result(
            session, "deepen", cardio_data, neuro_data,
            phase_summary="Cross-review complete.",
            warnings=warnings,
        )

    def phase_explore(self, session: LiveSession) -> dict:
        """Phase 3: Open exploration — 'What are we ALL blind to?'

        Both surgeons receive all prior analysis and surface unknown unknowns.
        Advances session to 'explore'.
        """
        session.advance_phase("explore")
        topic = session.topic
        warnings: List[str] = []

        # Build reports from accumulated findings for this iteration
        iter_findings = [
            f for f in session.accumulated_findings
            if f["iteration"] == session.current_iteration
        ]
        cardio_parts: List[str] = []
        neuro_parts: List[str] = []
        for f in iter_findings:
            if f.get("cardiologist"):
                items = f["cardiologist"] if isinstance(f["cardiologist"], list) else [str(f["cardiologist"])]
                cardio_parts.extend(items)
            if f.get("neurologist"):
                items = f["neurologist"] if isinstance(f["neurologist"], list) else [str(f["neurologist"])]
                neuro_parts.extend(items)

        cardio_report = "\n".join(cardio_parts) or "(no cardiologist findings)"
        neuro_report = "\n".join(neuro_parts) or "(no neurologist findings)"

        explore_prompt = _EXPLORATION_PROMPT.format(
            topic=topic,
            cardio_report=cardio_report,
            neuro_report=neuro_report,
        )

        cardio_resp = self._safe_query(
            self._cardiologist,
            system=_EXPLORATION_SYSTEM,
            prompt=explore_prompt,
        )
        neuro_resp = self._safe_query(
            self._neurologist,
            system=_EXPLORATION_SYSTEM,
            prompt=explore_prompt,
        )

        if cardio_resp is None and neuro_resp is None:
            warnings.append("Both surgeons unreachable during exploration.")
        else:
            if cardio_resp is None:
                warnings.append("Cardiologist unreachable during exploration.")
            if neuro_resp is None:
                warnings.append("Neurologist unreachable during exploration.")

        cardio_data = self._surgeon_data(cardio_resp)
        neuro_data = self._surgeon_data(neuro_resp)

        if cardio_resp:
            session.track_cost(cardio_resp.cost_usd)
            self._track_cost("cardiologist", cardio_resp.cost_usd, "phase_explore")
        if neuro_resp:
            session.track_cost(neuro_resp.cost_usd)
            self._track_cost("neurologist", neuro_resp.cost_usd, "phase_explore")

        session.add_finding(
            session.current_iteration, "explore",
            cardiologist=cardio_data["findings"],
            neurologist=neuro_data["findings"],
        )
        session.warnings.extend(warnings)

        return self._phased_result(
            session, "explore", cardio_data, neuro_data,
            phase_summary="Open exploration complete — unknown unknowns surfaced.",
            warnings=warnings,
        )

    def phase_synthesize(self, session: LiveSession) -> dict:
        """Phase 4: Synthesis + consensus score + iterate/done decision.

        Uses cardiologist for synthesis. Calculates consensus score.
        Advances session to 'synthesize'.
        """
        session.advance_phase("synthesize")
        topic = session.topic
        warnings: List[str] = []

        # Build reports from accumulated findings
        iter_findings = [
            f for f in session.accumulated_findings
            if f["iteration"] == session.current_iteration
        ]
        cardio_parts: List[str] = []
        neuro_parts: List[str] = []
        explore_cardio: List[str] = []
        explore_neuro: List[str] = []
        for f in iter_findings:
            is_explore = f["phase"] == "explore"
            if f.get("cardiologist"):
                items = f["cardiologist"] if isinstance(f["cardiologist"], list) else [str(f["cardiologist"])]
                if is_explore:
                    explore_cardio.extend(items)
                else:
                    cardio_parts.extend(items)
            if f.get("neurologist"):
                items = f["neurologist"] if isinstance(f["neurologist"], list) else [str(f["neurologist"])]
                if is_explore:
                    explore_neuro.extend(items)
                else:
                    neuro_parts.extend(items)

        cardio_report = "\n".join(cardio_parts) or "(no cardiologist findings)"
        neuro_report = "\n".join(neuro_parts) or "(no neurologist findings)"

        # Build exploration section
        exploration_parts = []
        if explore_cardio:
            exploration_parts.append(f"--- Cardiologist Exploration ---\n" + "\n".join(explore_cardio))
        if explore_neuro:
            exploration_parts.append(f"--- Neurologist Exploration ---\n" + "\n".join(explore_neuro))
        exploration_section = (
            "=== OPEN EXPLORATION (unknown unknowns) ===\n"
            + "\n\n".join(exploration_parts)
            + "\n\n"
            if exploration_parts
            else ""
        )

        # Synthesis via cardiologist
        synth_resp = self._safe_query(
            self._cardiologist,
            system=_SYNTHESIS_SYSTEM,
            prompt=_SYNTHESIS_PROMPT.format(
                topic=topic,
                cardio_report=cardio_report,
                neuro_report=neuro_report,
                exploration_section=exploration_section,
            ),
        )

        # Consensus via both surgeons (use original topic, not enriched)
        consensus_result = self.consensus(
            f"The analysis of '{session.original_topic}' is complete and all issues addressed."
        )
        score = consensus_result.weighted_score
        session.add_consensus_score(score)

        synth_data = self._surgeon_data(synth_resp)
        if synth_resp:
            session.track_cost(synth_resp.cost_usd)
            self._track_cost("cardiologist", synth_resp.cost_usd, "phase_synthesize")
        session.track_cost(consensus_result.total_cost)

        # Update confidence from consensus
        cardio_data = {
            "findings": synth_data["findings"] if synth_resp else [],
            "confidence": consensus_result.cardiologist_confidence,
            "cost_usd": (synth_resp.cost_usd if synth_resp else 0.0) + consensus_result.total_cost / 2,
            "latency_ms": synth_resp.latency_ms if synth_resp else 0,
            "status": "ok" if synth_resp else "unavailable",
        }
        neuro_data = {
            "findings": [],
            "confidence": consensus_result.neurologist_confidence,
            "cost_usd": consensus_result.total_cost / 2,
            "latency_ms": 0,
            "status": "ok" if consensus_result.neurologist_confidence > 0 else "unavailable",
        }

        if synth_resp is None:
            warnings.append("Synthesis failed — cardiologist unreachable.")

        session.add_finding(
            session.current_iteration, "synthesize",
            cardiologist=cardio_data["findings"],
            neurologist=neuro_data["findings"],
        )
        session.warnings.extend(warnings)

        next_action = session.next_action()
        summary = f"Consensus score: {score:.2f}. Next: {next_action}."

        result = self._phased_result(
            session, "synthesize", cardio_data, neuro_data,
            phase_summary=summary, warnings=warnings,
        )
        result["consensus_score"] = score
        return result

    def phase_iterate(self, session: LiveSession) -> dict:
        """Phase 5: Increment iteration, reset to 'start' with accumulated context.

        Builds the next iteration's topic by including prior findings.
        """
        session.current_iteration += 1
        session.advance_phase("start")

        # Build enriched topic with prior context
        prior_parts: List[str] = []
        for f in session.accumulated_findings:
            phase_label = f.get("phase", "?")
            iter_label = f.get("iteration", "?")
            items = []
            if f.get("cardiologist"):
                c = f["cardiologist"]
                items.append("Cardio: " + ("; ".join(c) if isinstance(c, list) else str(c)))
            if f.get("neurologist"):
                n = f["neurologist"]
                items.append("Neuro: " + ("; ".join(n) if isinstance(n, list) else str(n)))
            if items:
                prior_parts.append(f"[Iter {iter_label}/{phase_label}] " + " | ".join(items))

        prior_context = "\n".join(prior_parts)
        enriched_topic = (
            f"{session.original_topic}\n\n"
            f"=== Prior findings (iteration {session.current_iteration}/{session.max_iterations}) ===\n"
            f"{prior_context}"
        )

        # Store enriched topic for next phase_start to pick up (original preserved)
        session.topic = enriched_topic
        session.updated_at = datetime.now(timezone.utc).isoformat()

        return {
            "session_id": session.session_id,
            "phase": "start",
            "iteration": session.current_iteration,
            "cardiologist": {"findings": [], "confidence": 0.0, "cost_usd": 0.0, "latency_ms": 0, "status": "pending"},
            "neurologist": {"findings": [], "confidence": 0.0, "cost_usd": 0.0, "latency_ms": 0, "status": "pending"},
            "phase_summary": f"Iteration {session.current_iteration} ready. Topic enriched with prior findings.",
            "next_action": "start",
            "warnings": [],
        }

    # ── Private helpers ──────────────────────────────────────────────

    def _safe_query(
        self,
        provider: LLMProviderLike,
        system: str,
        prompt: str,
        max_tokens: int = 2048,
        temperature: float = 0.7,
        json_mode: bool = False,
    ) -> Optional[LLMResponseLike]:
        """Query a provider, returning None on failure instead of crashing.

        json_mode=True opts into provider-native JSON mode (response_format)
        when the underlying provider supports it (DeepSeek, OpenAI, Groq,
        Mistral, xAI). Eliminates prose wrapping for callers with strict
        schemas (consensus, AB validation). Provider-aware in models.py —
        unsupported providers fall through to standard call.
        """
        try:
            kwargs = {
                "system": system,
                "prompt": prompt,
                "max_tokens": max_tokens,
                "temperature": temperature,
            }
            # Only pass json_mode if the provider's query() accepts it.
            # Older provider stubs (or non-LLMProvider mocks) won't have it.
            try:
                import inspect
                if "json_mode" in inspect.signature(provider.query).parameters:
                    kwargs["json_mode"] = json_mode
            except (TypeError, ValueError):
                pass
            resp = provider.query(**kwargs)
            if not resp.ok:
                logger.warning(
                    "LLM query failed (model=%s): %s", resp.model, resp.content
                )
                return None
            return resp
        except Exception as exc:
            logger.error("Unexpected error querying LLM: %s", exc)
            return None

    @staticmethod
    def _build_report(
        initial: Optional[str],
        review: Optional[LLMResponseLike],
    ) -> Optional[str]:
        """Combine initial analysis with cross-review into a single report."""
        if initial is None:
            return None

        parts = [initial]
        if review is not None:
            parts.append(f"\n\n--- Cross-Review ---\n{review.content}")
        return "".join(parts)

    @staticmethod
    def _parse_consensus_json(content: str) -> dict:
        """Parse a surgeon's consensus JSON response.

        Handles models that wrap JSON in thinking text or markdown fences
        by extracting the first {...} block.

        Returns defaults on failure: confidence=0.0, assessment="unavailable".
        """
        text = content.strip()
        # Try direct parse first
        try:
            data = json.loads(text)
            return {
                "confidence": float(data.get("confidence", 0.0)),
                "assessment": str(data.get("assessment", "unavailable")),
            }
        except (json.JSONDecodeError, TypeError, ValueError):
            pass

        # Extract first JSON object from mixed content
        start = text.find("{")
        end = text.rfind("}")
        if start >= 0 and end > start:
            try:
                data = json.loads(text[start : end + 1])
                return {
                    "confidence": float(data.get("confidence", 0.0)),
                    "assessment": str(data.get("assessment", "unavailable")),
                }
            except (json.JSONDecodeError, TypeError, ValueError):
                pass

        logger.warning("Failed to parse consensus JSON: %s", content[:100])
        return {"confidence": 0.0, "assessment": "unavailable"}

    @staticmethod
    def _calculate_weighted_score(result: ConsensusResult) -> float:
        """Calculate a weighted consensus score from both surgeons' votes.

        Maps assessments to numeric values:
          agree=+1, uncertain=0, disagree=-1
        Then weights by confidence:
          score = sum(confidence_i * assessment_i) / sum(confidence_i)

        Returns 0.0 if total confidence is 0 (both unavailable).
        """
        assessment_map = {"agree": 1.0, "uncertain": 0.0, "disagree": -1.0}

        cardio_val = assessment_map.get(result.cardiologist_assessment, 0.0)
        neuro_val = assessment_map.get(result.neurologist_assessment, 0.0)

        total_confidence = (
            result.cardiologist_confidence + result.neurologist_confidence
        )
        if total_confidence == 0:
            return 0.0

        weighted = (
            result.cardiologist_confidence * cardio_val
            + result.neurologist_confidence * neuro_val
        ) / total_confidence

        return weighted

    def _track_cost(
        self, surgeon: str, cost_usd: float, operation: str
    ) -> None:
        """Track cost in the evidence store. Skip zero-cost (local models)."""
        if cost_usd > 0:
            self._evidence.track_cost(surgeon, cost_usd, operation)
        self._adapter.on_cost(surgeon, cost_usd, operation)

    def _check_confabulation(
        self,
        surgeon: str,
        question: str,
        answer: Optional[str],
        warnings: List[str],
    ) -> Optional[dict]:
        """Run confab detector on a surgeon answer.

        Side effects when confidence > 0.5:
          - Append warning to `warnings`.
          - Log a warning.
          - Increment a counter on the state backend so regressions show up
            in dashboards.

        Returns the report dict (or None if there was no answer).
        """
        if not answer:
            return None
        report = detect_confabulation(question, answer)
        if not report.confabulated:
            return None
        msg = (
            f"Confabulation suspected in {surgeon} answer "
            f"(confidence={report.confidence:.2f}, "
            f"signals={report.signals})"
        )
        warnings.append(msg)
        logger.warning(msg)
        try:
            self._state.increment("confab:total_flagged")
            self._state.increment(f"confab:by_surgeon:{surgeon}")
        except Exception as exc:  # pragma: no cover - state backend issues
            logger.warning("Failed to increment confab counter: %s", exc)
        return report.to_dict()

    def _log_cross_exam(self, result: CrossExamResult) -> None:
        """Log a cross-exam result to the evidence store."""
        self._evidence.record_cross_exam(
            topic=result.topic,
            neurologist_report=result.neurologist_report or "(unavailable)",
            cardiologist_report=result.cardiologist_report or "(unavailable)",
            consensus_score=getattr(result, 'consensus_score', 0.0),
            neurologist_exploration=result.neurologist_exploration or "",
            cardiologist_exploration=result.cardiologist_exploration or "",
        )
        self._adapter.on_cross_exam_logged(result.topic, {
            "consensus_score": getattr(result, 'consensus_score', 0.0),
            "iteration": getattr(result, 'iteration', 0),
        })
