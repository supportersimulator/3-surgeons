"""Tests for audit trail — structured tool invocation logging."""
import json
import time
from pathlib import Path

import pytest

from three_surgeons.core.audit import AuditTrail, AuditEntry


class TestAuditEntry:
    def test_entry_has_required_fields(self):
        entry = AuditEntry(
            tool="cross_examine",
            params={"topic": "test"},
            status="success",
            duration_ms=1500.0,
        )
        assert entry.tool == "cross_examine"
        assert entry.timestamp  # Auto-set
        assert entry.entry_id  # Auto-generated UUID
        assert entry.duration_ms == 1500.0

    def test_entry_serializes_to_dict(self):
        entry = AuditEntry(tool="probe", params={}, status="success")
        d = entry.to_dict()
        assert isinstance(d, dict)
        assert "timestamp" in d
        assert "entry_id" in d

    def test_entry_with_error(self):
        entry = AuditEntry(
            tool="cross_examine",
            params={"topic": "x"},
            status="error",
            error="Timeout",
        )
        assert entry.status == "error"
        assert entry.error == "Timeout"

    def test_entry_with_parent(self):
        parent = AuditEntry(tool="cross_examine", params={}, status="success")
        child = AuditEntry(
            tool="consult", params={}, status="success",
            parent_id=parent.entry_id,
        )
        assert child.parent_id == parent.entry_id


class TestAuditTrail:
    def test_record_and_retrieve(self, tmp_path: Path):
        trail = AuditTrail(storage_dir=str(tmp_path))
        entry = trail.record(tool="probe", params={}, status="success")
        entries = trail.recent(limit=10)
        assert len(entries) == 1
        assert entries[0]["tool"] == "probe"

    def test_recent_respects_limit(self, tmp_path: Path):
        trail = AuditTrail(storage_dir=str(tmp_path))
        for i in range(20):
            trail.record(tool=f"tool_{i}", params={}, status="success")
        entries = trail.recent(limit=5)
        assert len(entries) == 5

    def test_file_access_logged(self, tmp_path: Path):
        trail = AuditTrail(storage_dir=str(tmp_path))
        trail.record(
            tool="cross_examine",
            params={"topic": "test", "file_paths": ["/tmp/a.py"]},
            status="success",
            metadata={"files_read": 1, "total_chars": 500},
        )
        entries = trail.recent(limit=1)
        assert entries[0]["metadata"]["files_read"] == 1

    def test_jsonl_append_format(self, tmp_path: Path):
        trail = AuditTrail(storage_dir=str(tmp_path))
        trail.record(tool="a", params={}, status="success")
        trail.record(tool="b", params={}, status="error", error="fail")
        # Should be 2 lines in the JSONL file
        log_files = list(tmp_path.glob("audit-*.jsonl"))
        assert len(log_files) == 1
        lines = log_files[0].read_text().strip().split("\n")
        assert len(lines) == 2
        assert json.loads(lines[0])["tool"] == "a"
        assert json.loads(lines[1])["tool"] == "b"
