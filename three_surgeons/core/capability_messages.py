"""User-facing summary templates for capability changes and snapshots."""
from __future__ import annotations

from three_surgeons.core.capability_registry import CapabilityChange


def format_changes_message(
    changes: list[CapabilityChange], posture: str = "nominal"
) -> str:
    """Format a list of capability changes into a human-readable summary."""
    if not changes:
        return "No capability changes."

    lines: list[str] = [f"Capability changes (posture: {posture}):"]
    for c in changes:
        arrow = "\u2191" if c.is_upgrade else "\u2193"
        lines.append(f"  {arrow} {c.capability}: L{c.old_level} \u2192 L{c.new_level}")
        if c.user_summary:
            lines.append(f"    {c.user_summary}")
        if c.recovery_hint and not c.is_upgrade:
            lines.append(f"    Hint: {c.recovery_hint}")
    return "\n".join(lines)


def format_snapshot_message(snapshot: dict) -> str:
    """Format a registry snapshot dict into a readable status overview."""
    posture = snapshot.get("posture", "unknown")
    caps = snapshot.get("capabilities", {})

    lines: list[str] = [f"System posture: {posture}"]
    for name, info in caps.items():
        level = info.get("level", "?")
        marker = " *" if info.get("changed") else ""
        lines.append(f"  {name}: L{level}{marker}")
        change = info.get("change")
        if change:
            lines.append(
                f"    L{change['from']} \u2192 L{change['to']}: {change.get('summary', '')}"
            )
            recovery = change.get("recovery", "")
            if recovery:
                lines.append(f"    Hint: {recovery}")
    return "\n".join(lines)
