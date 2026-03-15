"""Dry-run mode — show what a tool would do without calling any LLM."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

# Cost estimates per tool (USD, based on gpt-4.1-mini pricing)
COST_ESTIMATES: dict[str, float] = {
    "probe": 0.001,
    "cross_examine": 0.006,
    "consult": 0.003,
    "consensus": 0.003,
    "sentinel_run": 0.001,
    "gains_gate": 0.001,
    "ab_propose": 0.003,
    "ab_start": 0.0,
    "ab_measure": 0.0,
    "ab_conclude": 0.001,
    "ab_validate_tool": 0.004,
    "ask_local_tool": 0.0,
    "ask_remote_tool": 0.002,
    "neurologist_pulse_tool": 0.0,
    "neurologist_challenge_tool": 0.002,
    "introspect_tool": 0.003,
    "cardio_review_tool": 0.003,
    "research_tool": 0.003,
    "upgrade_probe": 0.0,
    "upgrade_history": 0.0,
    "event_subscribe": 0.0,
    "event_unsubscribe": 0.0,
    "event_publish": 0.0,
    "event_poll": 0.0,
}

# Which surgeons each tool queries
TOOL_SURGEONS: dict[str, list[str]] = {
    "probe": ["neurologist", "cardiologist"],
    "cross_examine": ["neurologist", "cardiologist"],
    "consult": ["neurologist", "cardiologist"],
    "consensus": ["neurologist", "cardiologist"],
    "sentinel_run": ["neurologist"],
    "gains_gate": [],
    "ab_propose": ["neurologist", "cardiologist"],
    "ab_start": [],
    "ab_measure": [],
    "ab_conclude": ["neurologist", "cardiologist"],
    "ab_validate_tool": ["neurologist", "cardiologist"],
    "ask_local_tool": ["neurologist"],
    "ask_remote_tool": ["cardiologist"],
    "neurologist_pulse_tool": ["neurologist"],
    "neurologist_challenge_tool": ["neurologist"],
    "introspect_tool": ["neurologist", "cardiologist"],
    "cardio_review_tool": ["cardiologist"],
    "research_tool": ["cardiologist"],
    "upgrade_probe": [],
    "upgrade_history": [],
    "event_subscribe": [],
    "event_unsubscribe": [],
    "event_publish": [],
    "event_poll": [],
}


@dataclass
class DryRunResult:
    tool: str
    would_call: list[str] = field(default_factory=list)
    estimated_cost_usd: float = 0.0
    plan: str = ""
    dry_run: bool = True

    def to_dict(self) -> dict:
        return {
            "dry_run": True,
            "tool": self.tool,
            "would_call": self.would_call,
            "estimated_cost_usd": self.estimated_cost_usd,
            "plan": self.plan,
        }


def check_dry_run(tool_name: str, args: dict | None = None) -> DryRunResult:
    """Build a DryRunResult for the given tool (always returns a result).

    Called from CLI ``--dry-run`` handlers which have already checked the flag.
    """
    args = args or {}
    return DryRunResult(
        tool=tool_name,
        would_call=TOOL_SURGEONS.get(tool_name, []),
        estimated_cost_usd=COST_ESTIMATES.get(tool_name, 0.0),
        plan=f"Would invoke {tool_name} with args: {args}",
    )
