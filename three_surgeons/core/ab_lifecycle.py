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
