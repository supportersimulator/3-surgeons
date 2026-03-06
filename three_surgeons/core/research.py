"""Research and evidence cross-examination commands.

research: GPT-4.1 self-directed doc research with budget tracking.
cross_examine_evidence: Cross-examine docs against evidence store.
BudgetTracker: Daily spend tracking with configurable limits.
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from datetime import date
from typing import Any, Dict, List, Optional


@dataclass
class ResearchResult:
    """Outcome of a research query."""

    topic: str
    findings: List[str]
    sources: List[str]
    cost_usd: float
    raw_response: str


@dataclass
class EvidenceVerdict:
    """Verdict on a single claim against evidence."""

    claim: str
    verdict: str  # TRUE_TO_EVIDENCE | WORTH_TESTING | CONTRADICTS_EVIDENCE | NO_EVIDENCE | STALE
    confidence: float
    reasoning: str


@dataclass
class EvidenceCrossExamResult:
    """Outcome of cross-examining evidence."""

    topic: str
    verdicts: List[EvidenceVerdict]
    ab_test_candidates: List[str]
    cost_usd: float


class BudgetTracker:
    """Tracks daily research spend against a configurable budget.

    Uses the state backend for persistence.
    """

    def __init__(self, state_backend: Any, daily_limit_usd: float = 5.0) -> None:
        self._state = state_backend
        self._daily_limit = daily_limit_usd

    def _today_key(self) -> str:
        return f"research:costs:{date.today().isoformat()}"

    def spent_today(self) -> float:
        """Get total spend for today."""
        raw = self._state.get(self._today_key())
        if raw is None:
            return 0.0
        try:
            return float(raw)
        except (TypeError, ValueError):
            return 0.0

    def remaining(self) -> float:
        """Get remaining budget for today."""
        return max(0.0, self._daily_limit - self.spent_today())

    def can_afford(self, estimated_cost: float) -> bool:
        """Check if we can afford an estimated cost."""
        return self.remaining() >= estimated_cost

    def track(self, cost_usd: float, description: str = "") -> None:
        """Record a cost. Increments daily spend."""
        current = self.spent_today()
        new_total = current + cost_usd
        # Set with 48h TTL (covers timezone edge cases)
        self._state.set(self._today_key(), str(new_total), ttl=172800)


def research(
    topic: str,
    cardiologist: Any,
    file_index: Optional[List[Dict[str, str]]] = None,
) -> ResearchResult:
    """Run self-directed research on a topic.

    Optionally provides a file index (list of dicts with 'path' and 'summary')
    for the cardiologist to select relevant files from.
    """
    system = (
        "You are a research analyst. Given a topic and optionally a list of "
        "project files, provide key findings. Output JSON with: "
        "findings (list of strings), sources (list of relevant file paths or identifiers)."
    )
    prompt = f"Research topic: {topic}"
    if file_index:
        prompt += "\n\nAvailable files:\n"
        for f in file_index[:20]:  # Limit to 20 files
            prompt += f"- {f.get('path', 'unknown')}: {f.get('summary', '')[:100]}\n"

    try:
        resp = cardiologist.query(system=system, prompt=prompt, max_tokens=2048, temperature=0.5)
        raw = resp.content if resp.ok else ""
        cost = resp.cost_usd if resp.ok else 0.0
    except Exception:
        raw = ""
        cost = 0.0

    findings, sources = _parse_research(raw)
    return ResearchResult(
        topic=topic, findings=findings, sources=sources, cost_usd=cost, raw_response=raw
    )


def cross_examine_evidence(
    topic: str,
    cardiologist: Any,
    evidence_store: Any,
) -> EvidenceCrossExamResult:
    """Cross-examine documentation claims against evidence store.

    Searches evidence for the topic, then asks the cardiologist to evaluate
    each claim against the evidence.
    """
    # Get evidence snapshot
    try:
        snapshot = evidence_store.get_evidence_snapshot(topic, limit=20)
        evidence_text = snapshot.get("evidence_text", "")
    except Exception:
        evidence_text = ""

    system = (
        "You are cross-examining claims against evidence. For each claim you find, "
        "provide a verdict. Output JSON with: verdicts (array of objects with: "
        "claim, verdict (TRUE_TO_EVIDENCE|WORTH_TESTING|CONTRADICTS_EVIDENCE|"
        "NO_EVIDENCE|STALE), confidence (0.0-1.0), reasoning)."
    )
    prompt = f"Topic: {topic}\n\nEvidence:\n{evidence_text}"

    try:
        resp = cardiologist.query(system=system, prompt=prompt, max_tokens=2048, temperature=0.3)
        raw = resp.content if resp.ok else ""
        cost = resp.cost_usd if resp.ok else 0.0
    except Exception:
        raw = ""
        cost = 0.0

    verdicts = _parse_verdicts(raw)
    ab_candidates = [v.claim for v in verdicts if v.verdict == "WORTH_TESTING"]

    return EvidenceCrossExamResult(
        topic=topic, verdicts=verdicts, ab_test_candidates=ab_candidates, cost_usd=cost
    )


def _parse_research(raw: str) -> tuple:
    """Parse research JSON response into (findings, sources)."""
    if not raw:
        return ([], [])
    try:
        text = raw.strip()
        start = text.find("{")
        end = text.rfind("}")
        if start >= 0 and end > start:
            text = text[start : end + 1]
        data = json.loads(text)
        findings = list(data.get("findings", []))
        sources = list(data.get("sources", []))
        return (findings, sources)
    except (json.JSONDecodeError, TypeError, ValueError):
        return ([raw[:500]], [])


def _parse_verdicts(raw: str) -> List[EvidenceVerdict]:
    """Parse evidence verdicts from JSON response."""
    if not raw:
        return []
    try:
        text = raw.strip()
        start = text.find("{")
        end = text.rfind("}")
        if start >= 0 and end > start:
            text = text[start : end + 1]
        data = json.loads(text)
        verdicts_raw = data.get("verdicts", [])
        results = []
        for v in verdicts_raw:
            if isinstance(v, dict):
                results.append(
                    EvidenceVerdict(
                        claim=str(v.get("claim", "")),
                        verdict=str(v.get("verdict", "NO_EVIDENCE")),
                        confidence=float(v.get("confidence", 0.5)),
                        reasoning=str(v.get("reasoning", "")),
                    )
                )
        return results
    except (json.JSONDecodeError, TypeError, ValueError):
        return []
