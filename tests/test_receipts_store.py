"""Tests for three_surgeons/receipts/store.py — IJFW Phase 1 harvest."""
from __future__ import annotations

import json

import pytest

from three_surgeons.receipts.store import (
    MAX_RECEIPTS,
    ReceiptRecord,
    purge_receipts,
    read_receipts,
    receipts_file,
    render_receipt,
    render_receipts,
    write_receipt,
)


def test_receipts_file_path_shape(tmp_path):
    p = receipts_file(tmp_path)
    assert p == tmp_path / ".3-surgeons" / "receipts" / "cross-runs.jsonl"


def test_write_creates_dirs(tmp_path):
    rec = ReceiptRecord(mode="consult")
    dest = write_receipt(tmp_path, rec)
    assert dest.exists()
    assert dest.parent.is_dir()


def test_write_appends_one_jsonl_line(tmp_path):
    write_receipt(tmp_path, ReceiptRecord(mode="consult"))
    write_receipt(tmp_path, ReceiptRecord(mode="cross-exam"))
    text = receipts_file(tmp_path).read_text()
    lines = [line for line in text.split("\n") if line.strip()]
    assert len(lines) == 2
    assert json.loads(lines[0])["mode"] == "consult"
    assert json.loads(lines[1])["mode"] == "cross-exam"


def test_read_receipts_returns_dicts(tmp_path):
    write_receipt(tmp_path, ReceiptRecord(mode="consult", duration_ms=42))
    out = read_receipts(tmp_path)
    assert len(out) == 1
    assert out[0]["mode"] == "consult"
    assert out[0]["duration_ms"] == 42


def test_read_skips_corrupt_lines(tmp_path):
    dest = receipts_file(tmp_path)
    dest.parent.mkdir(parents=True)
    dest.write_text(
        '{"mode":"good"}\nNOT JSON\n{"mode":"also good"}\n'
    )
    out = read_receipts(tmp_path)
    assert [r["mode"] for r in out] == ["good", "also good"]


def test_purge_receipts_returns_count(tmp_path):
    write_receipt(tmp_path, ReceiptRecord(mode="a"))
    write_receipt(tmp_path, ReceiptRecord(mode="b"))
    n = purge_receipts(tmp_path)
    assert n == 2
    assert receipts_file(tmp_path).read_text() == ""


def test_purge_when_no_file_returns_zero(tmp_path):
    assert purge_receipts(tmp_path) == 0


def test_prune_keeps_last_n(tmp_path):
    for i in range(MAX_RECEIPTS + 5):
        write_receipt(tmp_path, ReceiptRecord(mode=f"r{i}"))
    out = read_receipts(tmp_path)
    assert len(out) == MAX_RECEIPTS
    # Oldest 5 should be dropped
    assert out[0]["mode"] == "r5"
    assert out[-1]["mode"] == f"r{MAX_RECEIPTS + 4}"


def test_record_to_dict_drops_none_fields():
    rec = ReceiptRecord(mode="consult")
    d = rec.to_dict()
    # `findings`, `duration_ms`, `cache_stats` were None → omitted
    assert "findings" not in d
    assert "duration_ms" not in d
    assert "cache_stats" not in d
    assert "mode" in d
    assert "timestamp" in d


def test_record_extra_hoists_to_top_level():
    rec = ReceiptRecord(mode="consult", extra={"task_id": "T-42"})
    d = rec.to_dict()
    assert d["task_id"] == "T-42"
    assert "extra" not in d


# ── Rendering ─────────────────────────────────────────────────────────────


def test_render_basic_consult():
    out = render_receipt({
        "mode": "consult",
        "timestamp": "2026-04-25T12:34:56.789Z",
        "auditors": [{"id": "cardio"}, {"id": "neuro"}],
        "duration_ms": 1234,
    })
    assert "3-Surgeons -- consult -- 2026-04-25 12:34:56" in out
    assert "auditors: cardio, neuro" in out
    assert "duration: 1s" in out


def test_render_findings_summary():
    out = render_receipt({
        "mode": "cross-exam",
        "findings": {"consensus": 3, "contested": 1, "unique": 2},
    })
    assert "3 consensus, 1 contested, 2 unique" in out


def test_render_findings_items_list():
    out = render_receipt({
        "mode": "consult",
        "findings": {"items": [{"x": 1}, {"x": 2}]},
    })
    assert "findings: 2 items" in out


def test_render_cache_stats_eligible_false():
    out = render_receipt({
        "mode": "consult",
        "cache_stats": {
            "cache_eligible": False,
            "cache_eligible_reason": "prompt < 1024 tokens",
        },
    })
    assert "cache-eligible: false" in out


def test_render_cache_stats_savings():
    out = render_receipt({
        "mode": "consult",
        "cache_stats": {
            "cache_creation_input_tokens": 500,
            "cache_read_input_tokens": 100_000,
        },
    })
    assert "cache created: 500 tokens" in out
    assert "cache read: 100000 tokens" in out
    assert "$0.27 saved" in out


def test_render_short_duration_in_ms():
    out = render_receipt({"mode": "consult", "duration_ms": 12})
    assert "duration: 12ms" in out


def test_render_handles_empty_record():
    """Render of {"mode": "x"} produces just the header without crashing."""
    out = render_receipt({"mode": "consult"})
    # Header always present
    assert out.startswith("3-Surgeons -- consult")


def test_render_receipts_separator():
    out = render_receipts([
        {"mode": "consult", "duration_ms": 100},
        {"mode": "cross-exam", "duration_ms": 200},
    ])
    # Two receipts joined by blank line
    assert out.count("3-Surgeons --") == 2
    assert "\n\n" in out
