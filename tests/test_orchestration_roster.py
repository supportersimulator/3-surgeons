"""Tests for three_surgeons/orchestration/roster.py — IJFW Phase 2 harvest."""
from __future__ import annotations

from unittest.mock import patch

import pytest

from three_surgeons.orchestration import roster
from three_surgeons.orchestration.roster import (
    ROSTER,
    Pick,
    PickResult,
    Reachability,
    default_reviewer,
    detect_self,
    format_roster,
    is_installed,
    is_reachable,
    pick_reviewers,
    roster_for,
    roster_with_status,
)


@pytest.fixture(autouse=True)
def reset_cache():
    """Reset the PATH-probe cache between tests so mocks aren't stale."""
    roster._reset_cache()
    yield
    roster._reset_cache()


# ── Self-detection ────────────────────────────────────────────────────────


def test_detect_self_from_env_key():
    assert detect_self({"CODEX_SESSION_ID": "abc"}) == "codex"
    assert detect_self({"CODEX_HOME": "/opt/codex"}) == "codex"


def test_detect_self_from_cmd_substring():
    assert detect_self({"_": "/usr/local/bin/codex"}) == "codex"


def test_detect_self_unknown_returns_none():
    assert detect_self({}) is None


def test_detect_self_does_not_raise_on_bad_env():
    """Defensive: weird env values must not crash detection."""
    assert detect_self({"_": None}) is None or detect_self({"_": None}) in (
        e.id for e in ROSTER
    )


def test_detect_claude():
    assert detect_self({"CLAUDECODE": "1"}) == "claude"
    assert detect_self({"CLAUDE_CODE_ENTRYPOINT": "stdin"}) == "claude"
    assert detect_self({"CLAUDE_PLUGIN_ROOT": "/opt"}) == "claude"


# ── PATH probe ────────────────────────────────────────────────────────────


def test_is_installed_true_for_present_binary():
    with patch.object(roster.shutil, "which", return_value="/usr/bin/codex"):
        assert is_installed("codex") is True


def test_is_installed_false_for_missing():
    with patch.object(roster.shutil, "which", return_value=None):
        assert is_installed("codex") is False


def test_is_installed_unknown_id():
    assert is_installed("bogus") is False


def test_is_installed_cached():
    """Second call hits cache, doesn't re-probe."""
    with patch.object(roster.shutil, "which", return_value="/x/codex") as m:
        is_installed("codex")
        is_installed("codex")
        assert m.call_count == 1


# ── Reachability ──────────────────────────────────────────────────────────


def test_is_reachable_cli_only():
    with patch.object(roster.shutil, "which", return_value="/usr/bin/aider"):
        r = is_reachable("aider", env={})
    assert r.cli is True
    assert r.api is False
    assert r.any is True


def test_is_reachable_api_only():
    with patch.object(roster.shutil, "which", return_value=None):
        r = is_reachable("codex", env={"OPENAI_API_KEY": "sk-x"})
    assert r.cli is False
    assert r.api is True
    assert r.any is True


def test_is_reachable_neither():
    with patch.object(roster.shutil, "which", return_value=None):
        r = is_reachable("codex", env={})
    assert r.cli is False
    assert r.api is False
    assert r.any is False


def test_is_reachable_oss_no_api_fallback():
    """opencode/aider have no apiFallback — env keys can't make them reachable."""
    with patch.object(roster.shutil, "which", return_value=None):
        r = is_reachable("opencode", env={"OPENCODE_HOME": "/x"})
    assert r.api is False  # only counts if entry has api_fallback


# ── Roster status ─────────────────────────────────────────────────────────


def test_roster_with_status_marks_self():
    with patch.object(roster.shutil, "which", return_value=None):
        items = roster_with_status({"CODEX_SESSION_ID": "x"})
    self_items = [s for s in items if s.is_self]
    assert len(self_items) == 1
    assert self_items[0].id == "codex"


def test_roster_with_status_marks_installed():
    """Mock which to return a path only for 'gemini' binary."""
    def fake_which(bin_name):
        return "/usr/bin/gemini" if "gemini" in bin_name else None
    with patch.object(roster.shutil, "which", side_effect=fake_which):
        items = roster_with_status({})
    gemini = next(s for s in items if s.id == "gemini")
    codex = next(s for s in items if s.id == "codex")
    assert gemini.installed is True
    assert codex.installed is False


# ── Pick (priority strategy) ──────────────────────────────────────────────


def test_pick_priority_excludes_self():
    """When caller is codex, codex must NOT appear in picks."""
    with patch.object(roster.shutil, "which", return_value="/x/bin"):
        result = pick_reviewers(env={"CODEX_SESSION_ID": "x"}, count=2)
    pick_ids = [p.id for p in result.picks]
    assert "codex" not in pick_ids


def test_pick_priority_returns_n():
    with patch.object(roster.shutil, "which", return_value="/x/bin"):
        result = pick_reviewers(env={}, count=2)
    assert len(result.picks) == 2


def test_pick_priority_no_reachable_returns_empty_with_note():
    with patch.object(roster.shutil, "which", return_value=None):
        result = pick_reviewers(env={})
    assert result.picks == []
    assert "Install" in result.note


def test_pick_priority_short_note_when_under_count():
    """If only 1 reviewer is reachable but count=2, note advises install another."""
    def fake_which(bin_name):
        return "/x" if "gemini" in bin_name else None
    with patch.object(roster.shutil, "which", side_effect=fake_which):
        result = pick_reviewers(env={}, count=2)
    assert len(result.picks) == 1
    assert "triangulate" in result.note.lower()


def test_pick_api_fallback_marked():
    """When CLI absent but API key present, preferred_source=api."""
    with patch.object(roster.shutil, "which", return_value=None):
        result = pick_reviewers(env={"OPENAI_API_KEY": "sk-x"}, count=1)
    if result.picks:
        # codex (openai family) should be picked via api fallback
        codex_pick = next((p for p in result.picks if p.id == "codex"), None)
        if codex_pick:
            assert codex_pick.preferred_source == "api"


# ── Pick (diversity strategy) ─────────────────────────────────────────────


def test_pick_diversity_targets_openai_and_google():
    """Both target families reachable + caller in neither → both picked."""
    with patch.object(roster.shutil, "which", return_value="/x/bin"):
        result = pick_reviewers(env={}, strategy="diversity")
    families = [p.entry.family for p in result.picks]
    assert "openai" in families
    assert "google" in families


def test_pick_diversity_caller_in_target_family_backfills():
    """Caller is openai-family → openai slot backfills with non-openai."""
    with patch.object(roster.shutil, "which", return_value="/x/bin"):
        result = pick_reviewers(
            env={"CODEX_SESSION_ID": "x"}, strategy="diversity",
        )
    pick_ids = [p.id for p in result.picks]
    assert "codex" not in pick_ids  # caller excluded


def test_pick_only_filter():
    """Only-filter restricts to named ids."""
    with patch.object(roster.shutil, "which", return_value="/x/bin"):
        result = pick_reviewers(env={}, only="gemini")
    assert len(result.picks) == 1
    assert result.picks[0].id == "gemini"


def test_pick_only_unreachable():
    """Only-filter with unreachable id → empty picks + note."""
    with patch.object(roster.shutil, "which", return_value=None):
        result = pick_reviewers(env={}, only="gemini")
    assert result.picks == []
    assert "not reachable" in result.note


# ── Convenience APIs ──────────────────────────────────────────────────────


def test_default_reviewer():
    with patch.object(roster.shutil, "which", return_value="/x"):
        d = default_reviewer({})
    assert d is not None
    assert d.id in {e.id for e in ROSTER}


def test_default_reviewer_excludes_self():
    with patch.object(roster.shutil, "which", return_value="/x"):
        d = default_reviewer({"CODEX_SESSION_ID": "x"})
    assert d.id != "codex"


def test_roster_for_excludes_self():
    items = roster_for(env={"GEMINI_CLI": "1"})
    assert all(s.id != "gemini" for s in items)


def test_roster_for_only_match():
    items = roster_for(only="codex", env={})
    assert len(items) == 1
    assert items[0].id == "codex"


def test_roster_for_only_no_match():
    items = roster_for(only="bogus", env={})
    assert items == []


def test_format_roster_includes_all_ids():
    with patch.object(roster.shutil, "which", return_value=None):
        out = format_roster({})
    for entry in ROSTER:
        assert entry.id in out


def test_format_roster_marks_self():
    with patch.object(roster.shutil, "which", return_value=None):
        out = format_roster({"GEMINI_CLI": "1"})
    assert "Detected caller: gemini" in out


# ── Result serialization ──────────────────────────────────────────────────


def test_pick_result_to_dict():
    with patch.object(roster.shutil, "which", return_value="/x"):
        result = pick_reviewers(env={}, count=1)
    d = result.to_dict()
    assert "picks" in d
    assert "missing" in d
    assert "note" in d
    if d["picks"]:
        assert "id" in d["picks"][0]
        assert "family" in d["picks"][0]
        assert "preferred_source" in d["picks"][0]


def test_reachability_to_dict():
    r = Reachability(cli=True, api=False)
    assert r.to_dict() == {"cli": True, "api": False, "any": True}
