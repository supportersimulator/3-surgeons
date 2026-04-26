"""Append-only JSONL receipts for cross-surgeon runs.

Ported from IJFW's ``mcp-server/src/receipts.js`` per the harvest plan
(2026-04-25 ContextDNA strategic doc).

WHY THIS EXISTS
---------------
3-Surgeons consults, cross-exams, and consensus runs need a durable
audit trail that:

* survives a single process crash,
* is greppable from a terminal (no SQLite required),
* doesn't grow unbounded,
* supports concurrent writers without a lock,
* renders to a human-readable summary on demand.

JSONL with ``open(..., "a")`` satisfies all five — POSIX guarantees
``write()`` ≤ ``PIPE_BUF`` (≥ 4 KB) is atomic, and a serialised receipt
record is well under that limit.

DESIGN
------
* One file per project: ``<project_dir>/.3-surgeons/receipts/cross-runs.jsonl``
* After every append, prune to the last :data:`MAX_RECEIPTS` lines.
* :func:`render_receipt` produces a multi-line text summary suitable for
  Discord, an email digest, or an evidence panel.
* :func:`read_receipts` skips corrupt lines instead of raising — the
  audit trail must remain usable even if one writer is buggy.

NOT GOALS
---------
* Not a query store — use :mod:`three_surgeons.retrieval.bm25` for that.
* Not a cross-machine log — Multi-Fleet handles distribution; this is
  per-node, file-system local.
"""
from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Sequence

logger = logging.getLogger(__name__)

#: Maximum receipts kept per project. Older entries are dropped on prune.
MAX_RECEIPTS: int = 100

#: Approximate Anthropic cache-read savings rate, USD per token.
#: Mirrors IJFW's hero-line.js constant — used in :func:`render_receipt`.
CACHE_SAVINGS_PER_TOKEN: float = 2.70 / 1_000_000


def receipts_file(project_dir: str | Path) -> Path:
    """Return the canonical receipts JSONL path for ``project_dir``."""
    return Path(project_dir) / ".3-surgeons" / "receipts" / "cross-runs.jsonl"


@dataclass
class ReceiptRecord:
    """Schema for one row in the JSONL store. Free-form metadata allowed
    via :attr:`extra`."""
    mode: str  #: "consult" | "cross-exam" | "consensus" | etc.
    timestamp: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    auditors: list[dict[str, Any]] = field(default_factory=list)
    findings: dict[str, Any] | None = None
    duration_ms: float | None = None
    cache_stats: dict[str, Any] | None = None
    extra: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        # Hoist `extra` keys to top-level for greppability; preserve schema
        # by not nesting metadata that doesn't need a namespace.
        extra = d.pop("extra") or {}
        d.update(extra)
        # Drop None fields so JSONL stays terse.
        return {k: v for k, v in d.items() if v is not None}


def write_receipt(project_dir: str | Path, record: ReceiptRecord | dict) -> Path:
    """Atomic append of one receipt; prune to :data:`MAX_RECEIPTS`.

    Returns the destination path so callers can chain (e.g. for logging).
    """
    dest = receipts_file(project_dir)
    dest.parent.mkdir(parents=True, exist_ok=True)
    payload = record.to_dict() if isinstance(record, ReceiptRecord) else dict(record)
    line = json.dumps(payload, ensure_ascii=False) + "\n"
    # POSIX guarantees atomic write up to PIPE_BUF on append-mode fd.
    # A typical receipt is < 1 KB, well under the 4 KB+ guarantee.
    with dest.open("a", encoding="utf-8") as fh:
        fh.write(line)
    _prune_receipts(dest)
    return dest


def _prune_receipts(dest: Path) -> None:
    """Trim to the last :data:`MAX_RECEIPTS` lines. No-op when at/under."""
    try:
        text = dest.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        logger.warning("receipts prune read failed: %s", exc)
        return
    lines = [line for line in text.split("\n") if line.strip()]
    if len(lines) <= MAX_RECEIPTS:
        return
    dest.write_text("\n".join(lines[-MAX_RECEIPTS:]) + "\n", encoding="utf-8")


def purge_receipts(project_dir: str | Path) -> int:
    """Empty the receipts file, returning the count of entries removed."""
    dest = receipts_file(project_dir)
    if not dest.exists():
        return 0
    text = dest.read_text(encoding="utf-8")
    count = sum(1 for line in text.split("\n") if line.strip())
    dest.write_text("", encoding="utf-8")
    return count


def read_receipts(project_dir: str | Path) -> list[dict[str, Any]]:
    """Read all receipts; corrupt lines are skipped (logged at debug)."""
    dest = receipts_file(project_dir)
    if not dest.exists():
        return []
    out: list[dict[str, Any]] = []
    text = dest.read_text(encoding="utf-8")
    for line in text.split("\n"):
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except (ValueError, TypeError) as exc:
            logger.debug("skipping corrupt receipt line: %s", exc)
    return out


def render_receipt(
    record: dict[str, Any],
    phase_label: str = "3-Surgeons",
    step_num: int = 1,
) -> str:
    """Multi-line human-readable summary of one receipt.

    JSONL schema is never modified — this is purely a presentation layer.
    """
    op = record.get("mode") or "cross"
    ts_raw = str(record.get("timestamp") or "")
    ts = ts_raw[:19].replace("T", " ") if ts_raw else ""
    lines = [f"{phase_label} -- {op} -- {ts}".rstrip(" -")]

    auditors = record.get("auditors")
    if isinstance(auditors, Sequence) and not isinstance(auditors, str):
        ids = ", ".join(
            str(a.get("id") or "") for a in auditors if isinstance(a, dict)
        ).strip(", ")
        if ids:
            lines.append(f"Step {step_num}.1 -- auditors: {ids}")

    findings = record.get("findings")
    if isinstance(findings, dict):
        items = findings.get("items")
        if isinstance(items, list):
            lines.append(f"Step {step_num}.2 -- findings: {len(items)} items")
        else:
            c = int(findings.get("consensus") or 0)
            ct = int(findings.get("contested") or 0)
            u = int(findings.get("unique") or 0)
            lines.append(
                f"Step {step_num}.2 -- findings: "
                f"{c} consensus, {ct} contested, {u} unique"
            )

    dur = record.get("duration_ms")
    if isinstance(dur, (int, float)):
        if dur < 1000:
            dur_str = f"{int(round(dur))}ms"
        else:
            dur_str = f"{int(round(dur / 1000))}s"
        lines.append(f"Step {step_num}.3 -- duration: {dur_str}")

    cs = record.get("cache_stats")
    if isinstance(cs, dict):
        if cs.get("cache_eligible") is False:
            reason = cs.get("cache_eligible_reason") or "prompt < 1024 tokens"
            lines.append(
                f"Step {step_num}.4 -- cache-eligible: false ({reason})"
            )
        else:
            create = cs.get("cache_creation_input_tokens")
            if isinstance(create, (int, float)):
                lines.append(
                    f"Step {step_num}.4 -- cache created: "
                    f"{int(create)} tokens"
                )
            read = cs.get("cache_read_input_tokens")
            if isinstance(read, (int, float)):
                saved = read * CACHE_SAVINGS_PER_TOKEN
                tail = f" (~${saved:.2f} saved)" if saved >= 0.01 else ""
                lines.append(
                    f"Step {step_num}.5 -- cache read: {int(read)} tokens{tail}"
                )

    return "\n".join(lines)


def render_receipts(
    records: Iterable[dict[str, Any]],
    phase_label: str = "3-Surgeons",
) -> str:
    """Render multiple receipts back-to-back with a blank-line separator."""
    return "\n\n".join(
        render_receipt(r, phase_label=phase_label, step_num=i + 1)
        for i, r in enumerate(records)
    )


__all__ = [
    "MAX_RECEIPTS",
    "ReceiptRecord",
    "purge_receipts",
    "read_receipts",
    "receipts_file",
    "render_receipt",
    "render_receipts",
    "write_receipt",
]
