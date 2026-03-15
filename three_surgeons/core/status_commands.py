"""Status display commands — pure state reads, zero LLM calls.

cmd_status: System health and capability overview
cmd_research_status: Research budget and cost tracking
"""
from __future__ import annotations

import json
import logging
from typing import Any, Dict

from three_surgeons.core.requirements import (
    CommandRequirements,
    CommandResult,
    RuntimeContext,
)

logger = logging.getLogger(__name__)

# ── Requirements ──────────────────────────────────────────────────────

STATUS_REQS = CommandRequirements(
    min_llms=0,
    needs_state=True,
    needs_evidence=False,
    needs_git=False,
)

RESEARCH_STATUS_REQS = CommandRequirements(
    min_llms=0,
    needs_state=True,
    needs_evidence=True,
    needs_git=False,
)


# ── Commands ──────────────────────────────────────────────────────────

def cmd_status(ctx: RuntimeContext) -> CommandResult:
    """System status: healthy surgeons, active tests, state backend info."""
    surgeons_info = {
        "healthy_count": len(ctx.healthy_llms),
        "models": [getattr(llm, "model", "unknown") for llm in ctx.healthy_llms],
    }

    # Active A/B test
    active_test = None
    raw = ctx.state.get("ab_test:active")
    if raw:
        try:
            active_test = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            pass

    # State backend type
    backend_type = type(ctx.state).__name__

    return CommandResult(
        success=True,
        data={
            "surgeons": surgeons_info,
            "active_ab_test": active_test,
            "state_backend": backend_type,
            "git_available": ctx.git_available,
            "git_root": ctx.git_root,
        },
    )


def cmd_research_status(ctx: RuntimeContext) -> CommandResult:
    """Research budget and cost tracking display."""
    budget_raw = ctx.state.get("research:budget")
    budget = None
    if budget_raw:
        try:
            budget = json.loads(budget_raw)
        except (json.JSONDecodeError, TypeError):
            pass

    recent_costs = []
    cost_list = ctx.state.list_range("research:costs", 0, 9)
    for entry in cost_list:
        try:
            recent_costs.append(json.loads(entry))
        except (json.JSONDecodeError, TypeError):
            continue

    evidence_stats = {}
    try:
        evidence_stats["total_learnings"] = len(ctx.evidence.search("", limit=0))
    except Exception:
        evidence_stats["total_learnings"] = "unavailable"

    return CommandResult(
        success=True,
        data={
            "budget": budget,
            "recent_costs": recent_costs,
            "evidence_stats": evidence_stats,
        },
    )
