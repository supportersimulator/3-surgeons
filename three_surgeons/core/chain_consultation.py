"""Surgeon consultation and community chain preset sync.

Every ~20 chain executions, 3 surgeons review usage patterns and suggest
novel chain sequences. Accepted chains are exported as YAML for community
sharing via git.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import yaml

from three_surgeons.core.requirements import (
    CommandRequirements,
    CommandResult,
    RuntimeContext,
)
from three_surgeons.core.state import StateBackend

logger = logging.getLogger(__name__)

# ── Consultation cadence ──────────────────────────────────────────────


def should_consult(state: StateBackend, cadence: int = 20) -> bool:
    """Check if it's time for a surgeon consultation."""
    total_raw = state.get("chain:total_executions")
    last_raw = state.get("chain:last_consultation_at")

    total = int(total_raw) if total_raw else 0
    last = int(last_raw) if last_raw else 0

    if total == 0:
        return False
    return (total - last) >= cadence


# ── Community Preset ──────────────────────────────────────────────────


@dataclass
class CommunityPreset:
    """A chain preset that can be shared with the community."""

    name: str
    segments: List[str]
    evidence_grade: str
    observations: int
    surgeon_consensus: float
    discovered_by: str
    tags: List[str] = field(default_factory=list)

    def to_yaml(self) -> str:
        """Serialize to YAML for community sharing."""
        return yaml.dump({
            "name": self.name,
            "segments": self.segments,
            "evidence_grade": self.evidence_grade,
            "observations": self.observations,
            "surgeon_consensus": self.surgeon_consensus,
            "discovered_by": self.discovered_by,
            "tags": self.tags,
        }, default_flow_style=False)

    @classmethod
    def from_yaml(cls, raw: str) -> "CommunityPreset":
        """Deserialize from YAML."""
        data = yaml.safe_load(raw)
        return cls(
            name=data["name"],
            segments=data["segments"],
            evidence_grade=data.get("evidence_grade", "anecdote"),
            observations=data.get("observations", 0),
            surgeon_consensus=data.get("surgeon_consensus", 0.0),
            discovered_by=data.get("discovered_by", "unknown"),
            tags=data.get("tags", []),
        )


# ── ChainConsultation ────────────────────────────────────────────────


class ChainConsultation:
    """Surgeon consultation on chain optimization + community sync."""

    def __init__(self, state: StateBackend) -> None:
        self._state = state

    def build_consultation_context(
        self,
        available_segments: List[str],
        current_presets: Dict[str, List[str]],
        recent_failures: List[Dict[str, Any]],
    ) -> str:
        """Build the prompt context for surgeon consultation."""
        lines = [
            "## Available Segments",
            ", ".join(available_segments),
            "",
            "## Current Presets",
        ]
        for name, segs in current_presets.items():
            lines.append(f"- {name}: {' -> '.join(segs)}")
        lines.append("")

        if recent_failures:
            lines.append("## Recent Failures")
            for fail in recent_failures[:10]:
                lines.append(
                    f"- {fail.get('segment', '?')}: {fail.get('error', '?')}"
                )

        return "\n".join(lines)

    def mark_consulted(self) -> None:
        """Record that consultation happened at current execution count."""
        total = self._state.get("chain:total_executions") or "0"
        self._state.set("chain:last_consultation_at", total)


# ── Meta-review segment requirements ─────────────────────────────────

META_REVIEW_REQS = CommandRequirements(
    min_llms=2,
    needs_state=True,
    needs_evidence=True,
    recommended_llms=3,
)
