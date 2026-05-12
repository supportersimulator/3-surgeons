"""ZSF counter persistence — surface 3-surgeons module-level counters to disk.

Why this exists (RR1 2026-05-08):
The 3-surgeons counters (``_NEURO_FALLBACK_COUNTERS``, ``DIVERSITY_COUNTERS``,
``_KEYCHAIN_ERRORS``) live in whatever Python process imports them. The fleet
daemon (``tools/fleet_nerve_nats.py``) runs in a *different* process, so it
cannot reach those module globals when it builds ``/health``. The result
before this fix: ZSF counters bumped silently and no fleet observer ever saw
them — defeating the entire ZSF invariant.

Solution (Option C from the RR1 plan): every counter increment side-effects
an atomic write to ``~/.3surgeons/zsf_counters.json``. The daemon reads that
file at /health build time. Simple, no port allocation, no shellout,
fault-tolerant.

ZSF for the persister itself: any persist failure (permission, ENOSPC, json
encode error, race) bumps a self-counter ``_persist_errors`` and silently
moves on. We never crash a counter increment because the counter export
broke — that would defeat the point.
"""
from __future__ import annotations

import json
import os
import tempfile
import threading
import time
from pathlib import Path
from typing import Any, Dict


# Single canonical file. Daemon reads from the same path.
_DEFAULT_PATH = Path.home() / ".3surgeons" / "zsf_counters.json"

# In-process self-counter. If file writes start failing, this counter spikes;
# the daemon side surfaces it as ``zsf_counters.three_surgeons.persist_errors``
# in /health when present.
_PERSIST_SELF: Dict[str, Any] = {
    "persist_errors": 0,
    "last_persist_error": "",
    "last_persist_ts": 0.0,
}

_persist_lock = threading.Lock()


def _target_path() -> Path:
    """Resolve persistence target. Override via env for tests."""
    override = os.environ.get("THREE_SURGEONS_ZSF_COUNTER_PATH")
    if override:
        return Path(override)
    return _DEFAULT_PATH


def persist_counters() -> None:
    """Write the current counter snapshot to disk atomically.

    Imports the live counter dicts lazily to avoid circular imports
    (config.py and diversity_canary.py both call this helper).

    Never raises. Failure paths bump ``_PERSIST_SELF['persist_errors']``.
    """
    try:
        # Lazy imports — these modules import this helper too. Doing the
        # imports inside the function avoids a top-level cycle.
        from three_surgeons.core import config as _cfg
        from three_surgeons.core import diversity_canary as _dc

        snapshot = {
            "neuro_fallback": dict(_cfg._NEURO_FALLBACK_COUNTERS),
            # AAA1 2026-05-12 — surface cardiologist fallback to /health.
            "cardio_fallback": dict(_cfg._CARDIO_FALLBACK_COUNTERS),
            "diversity": dict(_dc.DIVERSITY_COUNTERS),
            "keychain_errors": dict(_cfg._KEYCHAIN_ERRORS),
            "persist_self": dict(_PERSIST_SELF),
            "snapshot_ts": time.time(),
            "pid": os.getpid(),
        }
    except Exception as exc:  # noqa: BLE001 — ZSF
        with _persist_lock:
            _PERSIST_SELF["persist_errors"] = (
                _PERSIST_SELF.get("persist_errors", 0) + 1
            )
            _PERSIST_SELF["last_persist_error"] = f"snapshot: {exc!r}"
            _PERSIST_SELF["last_persist_ts"] = time.time()
        return

    target = _target_path()
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        # Atomic write via tempfile + os.replace. Avoids the
        # "daemon reads half-written file" race entirely.
        fd, tmp_path = tempfile.mkstemp(
            prefix=".zsf_counters.", suffix=".tmp", dir=str(target.parent)
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump(snapshot, fh, separators=(",", ":"))
            os.replace(tmp_path, target)
        except Exception:
            # Clean up tmp on failure; raise to outer handler.
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise
    except Exception as exc:  # noqa: BLE001 — ZSF
        with _persist_lock:
            _PERSIST_SELF["persist_errors"] = (
                _PERSIST_SELF.get("persist_errors", 0) + 1
            )
            _PERSIST_SELF["last_persist_error"] = f"write: {exc!r}"
            _PERSIST_SELF["last_persist_ts"] = time.time()


def read_counters() -> Dict[str, Any]:
    """Read the latest snapshot from disk. Used by the daemon at /health time.

    Returns ``{}`` if the file is missing, empty, malformed, or unreadable.
    Callers MUST treat the empty dict as "no signal yet" rather than an error.
    """
    target = _target_path()
    try:
        if not target.exists():
            return {}
        raw = target.read_text(encoding="utf-8").strip()
        if not raw:
            return {}
        data = json.loads(raw)
        if isinstance(data, dict):
            return data
        return {}
    except Exception:  # noqa: BLE001 — ZSF
        return {}


def get_persist_self() -> Dict[str, Any]:
    """Return a snapshot of the persister's own self-counters."""
    with _persist_lock:
        return dict(_PERSIST_SELF)
