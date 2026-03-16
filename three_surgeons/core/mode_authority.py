"""Mode presets, adaptive trigger detection, and per-project learning.

ModeAuthority resolves named presets into ordered segment lists,
detects triggers that suggest specific modes, and learns from user
acceptance/rejection of suggestions.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

from three_surgeons.core.state import StateBackend

logger = logging.getLogger(__name__)

# ── Built-in Presets ──────────────────────────────────────────────────

PRESETS: Dict[str, List[str]] = {
    "full-3s": [
        "pre-flight",
        "contradiction-scan",
        "risk-scan",
        "arch-gate",
        "plan-review",
        "pre-impl",
        "execute",
        "verify",
        "gains-gate",
        "doc-flow",
    ],
    "lightweight": ["pre-flight", "execute", "verify"],
    "plan-review": ["contradiction-scan", "plan-review", "pre-impl"],
    "evidence-dive": ["research-gather", "cross-check", "post-verify"],
}

# ── Trigger → Mode mapping ───────────────────────────────────────────

TRIGGER_MAP: Dict[str, str] = {
    "plan_file_detected": "plan-review",
    "large_task": "full-3s",
    "safety_critical": "full-3s",
    "test_only": "lightweight",
    "evidence_mismatch": "evidence-dive",
}


@dataclass
class Suggestion:
    """A mode suggestion from trigger detection."""

    mode: str
    trigger: str
    message: str


# ── ModeAuthority ────────────────────────────────────────────────────


class ModeAuthority:
    """Resolve presets, detect triggers, learn from user responses."""

    def __init__(self, state: StateBackend) -> None:
        self._state = state

    def resolve(
        self,
        mode: str,
        project_overrides: Dict[str, bool],
    ) -> List[str]:
        """Preset name -> ordered segment list with per-project toggles."""
        if mode not in PRESETS:
            raise KeyError(f"Unknown preset: {mode!r}. Available: {list(PRESETS)}")
        base = list(PRESETS[mode])
        for seg_name, enabled in project_overrides.items():
            if not enabled and seg_name in base:
                base.remove(seg_name)
            elif enabled and seg_name not in base:
                base.append(seg_name)
        return base

    def suggest(
        self,
        ctx: Any,  # RuntimeContext
        trigger: str,
    ) -> Optional[Suggestion]:
        """Detect opportunity and return suggestion, or None."""
        mode = TRIGGER_MAP.get(trigger)
        if mode is None:
            return None

        # Check if trigger conditions are actually met
        if trigger == "plan_file_detected" and ctx.git_root:
            plans = list(Path(ctx.git_root).glob("docs/plans/*.md"))
            if not plans:
                return None

        return Suggestion(
            mode=mode,
            trigger=trigger,
            message=f"{mode} available. Run? [y/N/always]",
        )

    def record_preference(self, mode: str, accepted: bool) -> None:
        """Record user acceptance/rejection for adaptive learning."""
        field = "accepted" if accepted else "ignored"
        self._state.hash_increment(f"mode:prefs:{mode}", field)

    def get_preference_stats(self, mode: str) -> Dict[str, int]:
        """Get acceptance/rejection counts for a mode."""
        raw = self._state.hash_get_all(f"mode:prefs:{mode}")
        return {
            "accepted": int(raw.get("accepted", "0")),
            "ignored": int(raw.get("ignored", "0")),
        }
