"""A/B test lifecycle commands.

Zero-LLM: ab-veto, ab-queue
Single-LLM: ab-start, ab-measure, ab-conclude
Multi-LLM: ab-collaborate
"""
from __future__ import annotations

import json
import logging
import time
from typing import Any, Dict, List, Optional

from three_surgeons.core.requirements import (
    CommandRequirements,
    CommandResult,
    RuntimeContext,
)

logger = logging.getLogger(__name__)

# ── Requirements ──────────────────────────────────────────────────────

AB_VETO_REQS = CommandRequirements(
    min_llms=0,
    needs_state=True,
    preconditions=["ab_test_exists"],
)

AB_QUEUE_REQS = CommandRequirements(
    min_llms=0,
    needs_state=True,
)

AB_START_REQS = CommandRequirements(
    min_llms=1,
    needs_state=True,
    needs_evidence=True,
    preconditions=["ab_test_proposed"],
    recommended_llms=1,
)

AB_MEASURE_REQS = CommandRequirements(
    min_llms=1,
    needs_state=True,
    needs_evidence=True,
    preconditions=["ab_test_active"],
    recommended_llms=2,
)

AB_CONCLUDE_REQS = CommandRequirements(
    min_llms=1,
    needs_state=True,
    needs_evidence=True,
    preconditions=["ab_test_active"],
    recommended_llms=2,
)

AB_COLLABORATE_REQS = CommandRequirements(
    min_llms=2,
    needs_state=True,
    needs_evidence=True,
    recommended_llms=3,
)

# ── Zero-LLM Commands ────────────────────────────────────────────────


def cmd_ab_veto(ctx: RuntimeContext, test_id: str, reason: str) -> CommandResult:
    """Veto an A/B test — state mutation only, no LLM needed."""
    raw = ctx.state.get(f"ab_test:{test_id}")
    if not raw:
        return CommandResult.blocked_result(
            f"No A/B test with ID '{test_id}'. Run `3s ab-queue` to list tests."
        )

    try:
        test_data = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return CommandResult.blocked_result(f"Corrupt test data for '{test_id}'.")

    test_data["status"] = "vetoed"
    test_data["veto_reason"] = reason
    test_data["vetoed_at"] = time.time()
    ctx.state.set(f"ab_test:{test_id}", json.dumps(test_data))

    return CommandResult(
        success=True,
        data={"vetoed_id": test_id, "reason": reason},
    )


def cmd_ab_queue(ctx: RuntimeContext) -> CommandResult:
    """List all A/B tests in the queue — read-only."""
    raw_list = ctx.state.list_range("ab_test:queue", 0, -1)
    tests: List[Dict[str, Any]] = []
    for raw in raw_list:
        try:
            tests.append(json.loads(raw))
        except (json.JSONDecodeError, TypeError):
            continue

    return CommandResult(
        success=True,
        data={"tests": tests, "count": len(tests)},
    )


# ── Single-LLM Commands ─────────────────────────────────────────────


def cmd_ab_start(
    ctx: RuntimeContext,
    test_id: str,
    duration_minutes: int = 30,
) -> CommandResult:
    """Start (activate) a proposed A/B test with grace period."""
    raw = ctx.state.get(f"ab_test:{test_id}")
    if not raw:
        return CommandResult.blocked_result(
            f"No A/B test with ID '{test_id}'. Run `3s ab-propose` first."
        )

    try:
        test_data = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return CommandResult.blocked_result(f"Corrupt test data for '{test_id}'.")

    if test_data.get("status") not in ("proposed", "grace_period"):
        return CommandResult.blocked_result(
            f"Test '{test_id}' is in status '{test_data.get('status')}', "
            f"expected 'proposed' or 'grace_period'."
        )

    # Transition to active
    now = time.time()
    test_data["status"] = "active"
    test_data["activated_at"] = now
    test_data["duration_minutes"] = duration_minutes
    test_data["expires_at"] = now + (duration_minutes * 60)

    # Record in state
    ctx.state.set(f"ab_test:{test_id}", json.dumps(test_data))
    ctx.state.set("ab_test:active", json.dumps(test_data))

    # Record activation in evidence
    if ctx.evidence:
        try:
            ctx.evidence.record_observation(
                topic=f"ab_test:{test_id}",
                observation=f"A/B test activated: {test_data.get('hypothesis', '')}",
                metadata={"duration_minutes": duration_minutes},
            )
        except Exception as exc:
            logger.warning("Failed to record activation in evidence: %s", exc)

    return CommandResult(
        success=True,
        data={
            "test_id": test_id,
            "status": "active",
            "activated_at": now,
            "duration_minutes": duration_minutes,
        },
    )


def cmd_ab_measure(ctx: RuntimeContext, test_id: str) -> CommandResult:
    """Measure an active A/B test — LLM assessment of evidence."""
    raw = ctx.state.get(f"ab_test:{test_id}")
    if not raw:
        return CommandResult.blocked_result(
            f"No A/B test with ID '{test_id}'."
        )

    try:
        test_data = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return CommandResult.blocked_result(f"Corrupt test data for '{test_id}'.")

    if test_data.get("status") != "active":
        return CommandResult.blocked_result(
            f"Test '{test_id}' is '{test_data.get('status')}', expected 'active'."
        )

    # Gather evidence
    evidence_items = []
    if ctx.evidence:
        try:
            evidence_items = ctx.evidence.search(f"ab_test:{test_id}", limit=20)
        except Exception:
            pass

    # LLM assessment
    assessment = "No LLM available for assessment"
    cost_usd = 0.0
    if ctx.healthy_llms:
        llm = ctx.healthy_llms[0]
        prompt = (
            f"A/B Test: {test_data.get('hypothesis', 'unknown')}\n"
            f"Parameter: {test_data.get('param', 'unknown')}\n"
            f"Variant A: {test_data.get('variant_a', '?')}\n"
            f"Variant B: {test_data.get('variant_b', '?')}\n"
            f"Evidence ({len(evidence_items)} items):\n"
        )
        for item in evidence_items[:10]:
            obs = item.get("observation", item.get("content", str(item)))
            prompt += f"- {obs}\n"
        prompt += "\nAssess progress. Which variant is performing better and why?"

        try:
            resp = llm.query(
                system="You are an A/B test analyst. Be concise and evidence-based.",
                prompt=prompt,
                max_tokens=512,
                temperature=0.3,
            )
            if resp.ok:
                assessment = resp.content
                cost_usd = resp.cost_usd
        except Exception as exc:
            logger.warning("LLM assessment failed: %s", exc)

    # Degradation notes
    degradation_notes = []
    if len(ctx.healthy_llms) < 2:
        degradation_notes.append(
            f"Running with {len(ctx.healthy_llms)} surgeon(s) "
            f"(2 recommended for cross-validation)."
        )

    return CommandResult(
        success=True,
        data={
            "test_id": test_id,
            "assessment": assessment,
            "evidence_count": len(evidence_items),
            "cost_usd": cost_usd,
        },
        degraded=bool(degradation_notes),
        degradation_notes=degradation_notes,
    )


def cmd_ab_conclude(
    ctx: RuntimeContext,
    test_id: str,
    verdict: str,
) -> CommandResult:
    """Conclude an A/B test with a verdict."""
    raw = ctx.state.get(f"ab_test:{test_id}")
    if not raw:
        return CommandResult.blocked_result(f"No A/B test with ID '{test_id}'.")

    try:
        test_data = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return CommandResult.blocked_result(f"Corrupt test data for '{test_id}'.")

    if test_data.get("status") != "active":
        return CommandResult.blocked_result(
            f"Test '{test_id}' is '{test_data.get('status')}', expected 'active'."
        )

    # Transition to concluded
    now = time.time()
    test_data["status"] = "concluded"
    test_data["concluded_at"] = now
    test_data["verdict"] = verdict

    ctx.state.set(f"ab_test:{test_id}", json.dumps(test_data))
    ctx.state.delete("ab_test:active")

    # Record in evidence
    if ctx.evidence:
        try:
            ctx.evidence.record_observation(
                topic=f"ab_test:{test_id}",
                observation=f"A/B test concluded: verdict={verdict}, hypothesis={test_data.get('hypothesis', '')}",
                metadata={"verdict": verdict, "test_id": test_id},
            )
        except Exception as exc:
            logger.warning("Failed to record conclusion in evidence: %s", exc)

    return CommandResult(
        success=True,
        data={
            "test_id": test_id,
            "verdict": verdict,
            "concluded_at": now,
        },
    )
