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


def _get_recent_git_files(git_root: str, days: int = 7, limit: int = 20) -> List[str]:
    """Get recently changed files from git log."""
    try:
        result = subprocess.run(
            ["git", "log", f"--since={days} days ago", "--name-only",
             "--pretty=format:", "--diff-filter=ACMR"],
            capture_output=True, text=True, timeout=10, cwd=git_root,
        )
        if result.returncode == 0:
            files = [f.strip() for f in result.stdout.strip().split("\n") if f.strip()]
            seen = set()
            unique = []
            for f in files:
                if f not in seen:
                    seen.add(f)
                    unique.append(f)
            return unique[:limit]
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass
    return []


def cmd_cardio_reverify(ctx: RuntimeContext, topic: str) -> CommandResult:
    """Multi-surgeon reverification of evidence against current codebase."""
    # Gather evidence
    evidence_items = []
    if ctx.evidence:
        try:
            evidence_items = ctx.evidence.search(topic, limit=20)
        except Exception:
            pass

    # Get recent git changes for context
    recent_files = []
    if ctx.git_root:
        recent_files = _get_recent_git_files(ctx.git_root)

    # Each surgeon assesses independently
    assessments = []
    total_cost = 0.0
    evidence_text = "\n".join(
        f"- [{item.get('grade', '?')}] {item.get('observation', str(item))}"
        for item in evidence_items[:15]
    )
    file_context = "\n".join(f"- {f}" for f in recent_files[:10]) if recent_files else "No recent changes"

    system_prompt = (
        "You are a surgeon reverifying evidence against current codebase state. "
        "Check if the evidence still holds given recent code changes. "
        "Flag any evidence that may be stale or contradicted by new code."
    )
    user_prompt = (
        f"Topic: {topic}\n\n"
        f"Evidence ({len(evidence_items)} items):\n{evidence_text}\n\n"
        f"Recent code changes:\n{file_context}"
    )

    for i, llm in enumerate(ctx.healthy_llms):
        try:
            resp = llm.query(
                system=system_prompt,
                prompt=user_prompt,
                max_tokens=768,
                temperature=0.3,
            )
            if resp.ok:
                assessments.append({
                    "surgeon_index": i,
                    "model": getattr(resp, "model", "unknown"),
                    "content": resp.content,
                    "cost_usd": resp.cost_usd,
                })
                total_cost += resp.cost_usd
        except Exception as exc:
            logger.warning("Surgeon %d failed during reverify: %s", i, exc)

    degradation_notes = []
    if len(ctx.healthy_llms) < 3:
        degradation_notes.append(
            f"Running with {len(ctx.healthy_llms)} surgeon(s) "
            f"(3 recommended for full cross-examination)."
        )

    return CommandResult(
        success=True,
        data={
            "topic": topic,
            "evidence_count": len(evidence_items),
            "assessments": assessments,
            "recent_files_checked": len(recent_files),
            "total_cost_usd": total_cost,
        },
        degraded=bool(degradation_notes),
        degradation_notes=degradation_notes,
    )
