"""Audit and research commands.

Single-LLM: research-evidence
Multi-LLM: cardio-reverify, deep-audit
"""
from __future__ import annotations

import json
import logging
import subprocess
from typing import Any, Dict, List, Optional

from three_surgeons.core.requirements import (
    CommandRequirements,
    CommandResult,
    RuntimeContext,
)

logger = logging.getLogger(__name__)

# ── Requirements ──────────────────────────────────────────────────────

RESEARCH_EVIDENCE_REQS = CommandRequirements(
    min_llms=1,
    needs_state=True,
    needs_evidence=True,
    recommended_llms=2,
)

CARDIO_REVERIFY_REQS = CommandRequirements(
    min_llms=2,
    needs_state=True,
    needs_evidence=True,
    needs_git=True,
    recommended_llms=3,
)

DEEP_AUDIT_REQS = CommandRequirements(
    min_llms=1,
    needs_state=True,
    needs_evidence=True,
    needs_git=True,
    recommended_llms=3,
)


# ── Commands ──────────────────────────────────────────────────────────

def cmd_research_evidence(ctx: RuntimeContext, topic: str) -> CommandResult:
    """Cross-check evidence store for a topic with LLM analysis."""
    # Gather evidence
    evidence_items = []
    if ctx.evidence:
        try:
            evidence_items = ctx.evidence.search(topic, limit=20)
        except Exception as exc:
            logger.warning("Evidence search failed: %s", exc)

    # LLM cross-examination of evidence
    analysis = "No LLM available for analysis"
    cost_usd = 0.0
    if ctx.healthy_llms and evidence_items:
        llm = ctx.healthy_llms[0]
        evidence_text = "\n".join(
            f"- {item.get('observation', item.get('content', str(item)))}"
            for item in evidence_items[:15]
        )
        try:
            resp = llm.query(
                system=(
                    "You are a research analyst. Cross-check the evidence below. "
                    "Identify patterns, contradictions, and confidence level."
                ),
                prompt=f"Topic: {topic}\n\nEvidence:\n{evidence_text}",
                max_tokens=768,
                temperature=0.3,
            )
            if resp.ok:
                analysis = resp.content
                cost_usd = resp.cost_usd
        except Exception as exc:
            logger.warning("LLM evidence analysis failed: %s", exc)
            analysis = f"LLM analysis failed: {exc}"

    degradation_notes = []
    if len(ctx.healthy_llms) < 2:
        degradation_notes.append(
            f"Running with {len(ctx.healthy_llms)} surgeon(s) "
            f"(2 recommended for cross-validation)."
        )

    return CommandResult(
        success=True,
        data={
            "topic": topic,
            "evidence_count": len(evidence_items),
            "analysis": analysis,
            "cost_usd": cost_usd,
        },
        degraded=bool(degradation_notes),
        degradation_notes=degradation_notes,
    )
