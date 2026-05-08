"""Smoke tests for ZSF counter persistence (RR1 2026-05-08).

Counters from ``config.py`` (_NEURO_FALLBACK_COUNTERS, _KEYCHAIN_ERRORS) and
``diversity_canary.py`` (DIVERSITY_COUNTERS) live in module globals — invisible
to the fleet daemon, which runs in a different process. Option C of the RR1
plan: every counter increment writes ``~/.3surgeons/zsf_counters.json``
atomically; the daemon reads that file at /health build time.

These tests verify:
  1. The persister writes a valid JSON snapshot containing all three counter
     groups + a ``persist_self`` block.
  2. ``read_counters()`` round-trips the snapshot back.
  3. Bumping a real counter (diversity_canary.evaluate_diversity) propagates
     the change to disk.
  4. ZSF: a broken target path (read-only) does NOT raise — it bumps the
     persister's own self-counter instead.
  5. ZSF: read_counters() returns ``{}`` for missing/malformed/empty files.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest


def _setup_counter_path(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    """Point the persister at a test-local file."""
    target = tmp_path / "zsf_counters.json"
    monkeypatch.setenv("THREE_SURGEONS_ZSF_COUNTER_PATH", str(target))
    return target


def test_persist_writes_all_counter_groups(monkeypatch, tmp_path):
    """persist_counters() emits a JSON file with every counter group."""
    target = _setup_counter_path(monkeypatch, tmp_path)

    from three_surgeons.core.zsf_counter_persist import persist_counters

    persist_counters()

    assert target.exists(), "persist_counters() must create the snapshot file"
    data = json.loads(target.read_text(encoding="utf-8"))

    # Required top-level keys
    for key in ("neuro_fallback", "diversity", "keychain_errors",
                "persist_self", "snapshot_ts", "pid"):
        assert key in data, f"snapshot missing key: {key}"

    # Neuro fallback contract — 6 keys per QQ1
    for k in ("ollama", "mlx", "mlx_proxy", "deepseek",
              "default_kept", "no_provider_reachable"):
        assert k in data["neuro_fallback"], f"neuro_fallback missing {k}"

    # Diversity contract — 5 keys per QQ3
    for k in ("consensus_total", "same_provider_same_model",
              "byte_identical_replies", "verdict_agree_no_caveats",
              "yellow_signals_total"):
        assert k in data["diversity"], f"diversity missing {k}"

    # Keychain — count + last (merge-resolve)
    assert "count" in data["keychain_errors"]
    assert "last" in data["keychain_errors"]

    # Persister self-health block
    assert "persist_errors" in data["persist_self"]


def test_read_counters_roundtrips(monkeypatch, tmp_path):
    """read_counters() returns the dict that persist_counters() wrote."""
    _setup_counter_path(monkeypatch, tmp_path)

    from three_surgeons.core.zsf_counter_persist import (
        persist_counters, read_counters,
    )

    persist_counters()
    snap = read_counters()

    assert isinstance(snap, dict)
    assert "neuro_fallback" in snap
    assert "diversity" in snap


def test_bumping_diversity_counter_propagates_to_disk(monkeypatch, tmp_path):
    """evaluate_diversity() bumps and persists in one step."""
    target = _setup_counter_path(monkeypatch, tmp_path)

    from three_surgeons.core import diversity_canary as dc

    dc.reset_diversity_counters()
    before = dict(dc.DIVERSITY_COUNTERS)
    assert before["consensus_total"] == 0

    dc.evaluate_diversity(
        cardio_reply={"text": "agree", "verdict": "agree", "caveats": []},
        neuro_reply={"text": "agree", "verdict": "agree", "caveats": []},
        cardio_cfg={"provider": "deepseek", "model": "deepseek-chat"},
        neuro_cfg={"provider": "deepseek", "model": "deepseek-chat"},
    )

    assert dc.DIVERSITY_COUNTERS["consensus_total"] == 1
    assert target.exists()
    snap = json.loads(target.read_text(encoding="utf-8"))
    assert snap["diversity"]["consensus_total"] == 1
    # Two yellow signals tripped (model-collapse + byte-identical + frictionless).
    assert snap["diversity"]["yellow_signals_total"] >= 1


def test_persist_zsf_on_unwritable_path(monkeypatch, tmp_path):
    """Broken target path must NOT crash — bump persist_errors and move on."""
    # Point at a path where the parent dir is a regular FILE — mkdir(parents=)
    # will fail when the persister tries to create the parent.
    blocker = tmp_path / "blocker"
    blocker.write_text("not a dir", encoding="utf-8")
    bad_target = blocker / "zsf_counters.json"
    monkeypatch.setenv("THREE_SURGEONS_ZSF_COUNTER_PATH", str(bad_target))

    from three_surgeons.core.zsf_counter_persist import (
        persist_counters, get_persist_self,
    )

    before = get_persist_self().get("persist_errors", 0)
    # Must not raise.
    persist_counters()
    after = get_persist_self().get("persist_errors", 0)

    assert after == before + 1, "persist_errors must bump on write failure"


def test_read_counters_returns_empty_on_missing_file(monkeypatch, tmp_path):
    """ZSF: missing file → empty dict, never raises."""
    _setup_counter_path(monkeypatch, tmp_path)

    from three_surgeons.core.zsf_counter_persist import read_counters

    snap = read_counters()
    assert snap == {}


def test_read_counters_returns_empty_on_malformed_json(monkeypatch, tmp_path):
    """ZSF: malformed JSON → empty dict, never raises."""
    target = _setup_counter_path(monkeypatch, tmp_path)
    target.write_text("not valid json {{{", encoding="utf-8")

    from three_surgeons.core.zsf_counter_persist import read_counters

    snap = read_counters()
    assert snap == {}


def test_read_counters_returns_empty_on_empty_file(monkeypatch, tmp_path):
    """ZSF: zero-byte file → empty dict."""
    target = _setup_counter_path(monkeypatch, tmp_path)
    target.write_text("", encoding="utf-8")

    from three_surgeons.core.zsf_counter_persist import read_counters

    snap = read_counters()
    assert snap == {}
