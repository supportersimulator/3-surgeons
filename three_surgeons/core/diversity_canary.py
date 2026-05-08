"""Diversity canary — flags when 3-surgeon consensus collapses.

Sidecar to INV-006. Does NOT fail consensus. Emits YELLOW telemetry to
module-level counters (ZSF — never raises) so ``3s diversity-status``
and ``3s bridge-status`` can surface collapse patterns post-neuro
cutover (CLAUDE.md 2026-04-26: deepseek-on-both is the local steady
state — INV-006 still passes, but model diversity is gone).

Design contract:
- Pure function ``evaluate_diversity`` — no exceptions on bad input.
- Counters live at module scope (mirror of ``_KEYCHAIN_ERRORS`` in
  ``core/config.py``). Per-PID; surfaced via ``get_diversity_status()``.
- Reversible kill-switch — set ``CONTEXT_DNA_DIVERSITY_CANARY=off`` to
  turn the canary into a no-op (still bumps ``consensus_total`` so
  rate-of-evaluation telemetry stays honest).
- Stderr-only emission from the call site — Aaron greps; agents
  parsing stdout don't see the warning. This module owns the COUNTERS;
  the caller owns the stderr line.

Yellow signals (any one trips ``yellow=True``):
1. ``model collapse`` — both surgeons share provider AND model
   (diversity guarantee impossible — same weights, same priors).
2. ``byte-identical`` — surgeons returned the same reply text.
3. ``frictionless`` — both verdicts == "agree" with zero caveats
   (suspiciously clean — the value of 3-surgeons IS the friction).
"""
from __future__ import annotations

import os
from typing import Any, Dict, List, Optional

# Module-level ZSF counters (per-PID). Mirrors _KEYCHAIN_ERRORS pattern.
DIVERSITY_COUNTERS: Dict[str, int] = {
    "consensus_total": 0,
    "same_provider_same_model": 0,
    "byte_identical_replies": 0,
    "verdict_agree_no_caveats": 0,
    "yellow_signals_total": 0,
}


def _persist_counters_zsf() -> None:
    """ZSF best-effort: surface counters to disk for the fleet daemon.

    See ``zsf_counter_persist`` for rationale. Lazy import keeps this
    file independent at module-load time. Failures inside the persister
    are absorbed there; this wrapper protects against import errors.
    """
    try:
        from three_surgeons.core.zsf_counter_persist import persist_counters
        persist_counters()
    except Exception:  # noqa: BLE001 — ZSF
        pass


def _safe_get(obj: Any, *names: str, default: str = "") -> str:
    """Best-effort attribute/key lookup. Always returns a string."""
    if obj is None:
        return default
    for name in names:
        # Dict-style
        if isinstance(obj, dict):
            val = obj.get(name)
            if val is not None:
                return str(val)
            continue
        # Attribute-style
        try:
            val = getattr(obj, name, None)
        except Exception:  # noqa: BLE001 — ZSF: never raise from canary
            val = None
        if val is not None and val != "":
            return str(val)
    return default


def _disabled() -> bool:
    """Reversible kill-switch. ``CONTEXT_DNA_DIVERSITY_CANARY=off`` disables."""
    return os.environ.get("CONTEXT_DNA_DIVERSITY_CANARY", "").strip().lower() == "off"


def evaluate_diversity(
    cardio_reply: Optional[Dict[str, Any]],
    neuro_reply: Optional[Dict[str, Any]],
    cardio_cfg: Any,
    neuro_cfg: Any,
) -> Dict[str, Any]:
    """Return ``{'yellow': bool, 'reasons': [str, ...]}``.

    Bumps module counters as a side effect. Never raises — bad input
    yields ``{'yellow': False, 'reasons': []}`` and a clean increment
    of ``consensus_total``.
    """
    DIVERSITY_COUNTERS["consensus_total"] = (
        DIVERSITY_COUNTERS.get("consensus_total", 0) + 1
    )

    if _disabled():
        _persist_counters_zsf()
        return {"yellow": False, "reasons": []}

    reasons: List[str] = []

    # Reply shape — defensively coerce to dicts.
    cardio_reply = cardio_reply if isinstance(cardio_reply, dict) else {}
    neuro_reply = neuro_reply if isinstance(neuro_reply, dict) else {}

    cardio_provider = _safe_get(cardio_cfg, "provider", "_provider")
    neuro_provider = _safe_get(neuro_cfg, "provider", "_provider")
    cardio_model = _safe_get(cardio_cfg, "model")
    neuro_model = _safe_get(neuro_cfg, "model")

    # Signal 1 — model collapse
    if (
        cardio_provider
        and neuro_provider
        and cardio_provider == neuro_provider
        and cardio_model
        and neuro_model
        and cardio_model == neuro_model
    ):
        DIVERSITY_COUNTERS["same_provider_same_model"] = (
            DIVERSITY_COUNTERS.get("same_provider_same_model", 0) + 1
        )
        reasons.append(
            f"model collapse — both surgeons on {cardio_provider}/{cardio_model}"
        )

    # Signal 2 — byte-identical replies
    cardio_text = str(cardio_reply.get("text") or "").strip()
    neuro_text = str(neuro_reply.get("text") or "").strip()
    if cardio_text and neuro_text and cardio_text == neuro_text:
        DIVERSITY_COUNTERS["byte_identical_replies"] = (
            DIVERSITY_COUNTERS.get("byte_identical_replies", 0) + 1
        )
        reasons.append(
            f"byte-identical replies ({len(cardio_text)} chars)"
        )

    # Signal 3 — frictionless agreement
    cardio_verdict = str(cardio_reply.get("verdict") or "").strip().lower()
    neuro_verdict = str(neuro_reply.get("verdict") or "").strip().lower()
    cardio_caveats = cardio_reply.get("caveats")
    neuro_caveats = neuro_reply.get("caveats")
    cardio_caveats = cardio_caveats if isinstance(cardio_caveats, list) else []
    neuro_caveats = neuro_caveats if isinstance(neuro_caveats, list) else []
    if (
        cardio_verdict == "agree"
        and neuro_verdict == "agree"
        and len(cardio_caveats) == 0
        and len(neuro_caveats) == 0
    ):
        DIVERSITY_COUNTERS["verdict_agree_no_caveats"] = (
            DIVERSITY_COUNTERS.get("verdict_agree_no_caveats", 0) + 1
        )
        reasons.append("frictionless — both agree, zero caveats")

    yellow = bool(reasons)
    if yellow:
        DIVERSITY_COUNTERS["yellow_signals_total"] = (
            DIVERSITY_COUNTERS.get("yellow_signals_total", 0) + 1
        )
    # ZSF: persist the post-evaluation snapshot so the daemon's /health
    # reflects the latest yellow / agreement signal even if this PID dies.
    _persist_counters_zsf()
    return {"yellow": yellow, "reasons": reasons}


def get_diversity_status() -> Dict[str, Any]:
    """Snapshot the canary counters for surfacing in CLI status commands."""
    return {
        "enabled": not _disabled(),
        "counters": dict(DIVERSITY_COUNTERS),
    }


def reset_diversity_counters() -> None:
    """Test helper — reset all counters to zero. Production code does not call this."""
    for key in DIVERSITY_COUNTERS:
        DIVERSITY_COUNTERS[key] = 0
