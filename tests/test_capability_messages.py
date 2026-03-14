"""Tests for capability_messages — user-facing summary templates."""
from three_surgeons.core.capability_registry import CapabilityChange
from three_surgeons.core.capability_messages import (
    format_changes_message,
    format_snapshot_message,
)


def _upgrade() -> CapabilityChange:
    return CapabilityChange(
        capability="cross_exam",
        old_level=1,
        new_level=3,
        reason="cardiologist available",
        user_summary="Full 3-surgeon cross-examination",
        recovery_hint="",
    )


def _downgrade() -> CapabilityChange:
    return CapabilityChange(
        capability="state_backend",
        old_level=3,
        new_level=1,
        reason="redis down",
        user_summary="Local state only",
        recovery_hint="Start Redis: docker compose up -d redis",
    )


class TestFormatChangesMessage:
    def test_upgrades(self):
        msg = format_changes_message([_upgrade()])
        assert "nominal" in msg.lower()
        assert "\u2191" in msg  # up arrow
        assert "cross_exam" in msg
        assert "Full 3-surgeon cross-examination" in msg

    def test_downgrades_with_recovery_hint(self):
        msg = format_changes_message([_downgrade()])
        assert "\u2193" in msg  # down arrow
        assert "state_backend" in msg
        assert "Local state only" in msg
        assert "Start Redis" in msg

    def test_no_changes(self):
        msg = format_changes_message([])
        assert "no capability changes" in msg.lower()

    def test_mixed_upgrades_and_downgrades(self):
        msg = format_changes_message([_upgrade(), _downgrade()])
        assert "\u2191" in msg
        assert "\u2193" in msg
        assert "cross_exam" in msg
        assert "state_backend" in msg

    def test_posture_in_header(self):
        msg = format_changes_message([_upgrade()], posture="degraded")
        assert "degraded" in msg.lower()


class TestFormatSnapshotMessage:
    def test_snapshot_message(self):
        snapshot = {
            "posture": "nominal",
            "capabilities": {
                "cross_exam": {"level": 3, "changed": False},
                "state_backend": {
                    "level": 1,
                    "changed": True,
                    "change": {
                        "from": 2,
                        "to": 1,
                        "summary": "Local state only",
                        "recovery": "Start Redis",
                    },
                },
            },
        }
        msg = format_snapshot_message(snapshot)
        assert "nominal" in msg.lower()
        assert "cross_exam" in msg
        assert "L3" in msg
        assert "state_backend" in msg
        assert "L1" in msg
