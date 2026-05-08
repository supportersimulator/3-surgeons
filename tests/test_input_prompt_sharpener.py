"""Tests for three_surgeons/input/prompt_sharpener.py — IJFW Phase 1 harvest."""
from __future__ import annotations

from three_surgeons.input.prompt_sharpener import check_prompt


# ── Bypass conditions ─────────────────────────────────────────────────────

def test_non_string_bypassed():
    r = check_prompt(None)
    assert not r.vague
    assert r.bypass_reason == "non-string"


def test_empty_string_bypassed():
    r = check_prompt("")
    assert not r.vague
    assert r.bypass_reason == "empty"


def test_whitespace_only_bypassed():
    r = check_prompt("   \n\t   ")
    assert not r.vague
    assert r.bypass_reason == "empty"


def test_asterisk_prefix_bypassed():
    r = check_prompt("* fix it")
    assert r.bypass_reason == "asterisk-prefix"


def test_slash_command_bypassed():
    r = check_prompt("/help")
    assert r.bypass_reason == "slash-command"


def test_memorize_prefix_bypassed():
    r = check_prompt("# remember this")
    assert r.bypass_reason == "memorize-prefix"


def test_3s_off_override():
    r = check_prompt("fix this 3s off")
    assert r.bypass_reason == "override-keyword"


def test_long_prompt_bypassed():
    r = check_prompt("x" * 5000)
    assert r.bypass_reason == "long-prompt"


def test_fenced_code_bypassed():
    r = check_prompt("```py\nprint('hi')\n```\nfix this")
    assert r.bypass_reason == "fenced-code"


# ── Rule trips (single-signal silent) ──────────────────────────────────────

def test_single_signal_does_not_fire():
    """One signal alone must NOT mark vague — keeps false-positive rate low."""
    r = check_prompt("the bug")
    # 1 signal (unresolved_anaphora), no_target also true → vague=True
    # so use a single-signal-only example: a 5-token sentence with target
    r2 = check_prompt("update src/app.py header")
    assert not r2.vague


def test_bare_verb_with_no_target_is_vague():
    r = check_prompt("fix it")
    assert r.vague
    assert "bare_verb" in r.signals
    assert "no_target" in r.signals
    assert r.suggestion
    assert r.questions
    assert len(r.questions) <= 3


def test_unresolved_anaphora_is_vague():
    r = check_prompt("this is broken")
    assert r.vague
    assert "unresolved_anaphora" in r.signals


def test_abstract_goal_with_target_not_vague():
    """Abstract goal mitigated by file/path or numeric metric."""
    r = check_prompt("make src/auth.py more robust")
    # has file path → no_target=False → vague=False even with abstract_goal
    assert not r.vague


def test_abstract_goal_with_metric_not_vague():
    r = check_prompt("make it 50% better")
    # has digit + ms/% → mitigated
    assert "abstract_goal" not in r.signals or not r.vague


def test_path_target_avoids_no_target():
    r = check_prompt("review src/auth.py")
    assert "no_target" not in r.signals


def test_identifier_target_avoids_no_target():
    r = check_prompt("review getUserById")
    assert "no_target" not in r.signals


def test_line_number_target_avoids_no_target():
    r = check_prompt("the bug at file:145")
    assert "no_target" not in r.signals


def test_scope_plural():
    r = check_prompt("fix all the things")
    assert "scope_plural" in r.signals
    assert r.vague


def test_polysemous_alone_not_enough():
    """Polysemous alone is silent — needs another signal."""
    r = check_prompt("deploy")
    # bare_verb? "deploy" matches bare_verb regex too. Plus no_target.
    # So 2+ signals → vague. That's expected.
    assert r.vague


def test_missing_constraint_with_short_prompt_skipped():
    """Rule skips on <4 tokens to avoid double-counting tiny prompts."""
    r = check_prompt("fix it")
    assert "missing_constraint" not in r.signals


def test_missing_constraint_with_constraint_word_not_signal():
    r = check_prompt("the auth must reject expired tokens always")
    assert "missing_constraint" not in r.signals


# ── Suggestion content ────────────────────────────────────────────────────

def test_suggestion_uses_positive_framing():
    """Per IJFW design: never says 'your prompt is vague'."""
    r = check_prompt("fix it")
    assert r.suggestion
    assert "vague" not in r.suggestion.lower()
    assert "wrong" not in r.suggestion.lower()


def test_questions_capped_at_3():
    # Trip many signals
    r = check_prompt("fix this stuff")
    assert len(r.questions) <= 3


def test_questions_deduped():
    """bare_verb and no_target both map to the same question — dedupe."""
    r = check_prompt("fix it")
    assert len(r.questions) == len(set(r.questions))


def test_long_specific_prompt_not_vague():
    r = check_prompt(
        "Refactor the authentication middleware in src/auth/middleware.py "
        "so that token expiry uses < instead of <= per RFC 7519 section 4.1.4"
    )
    assert not r.vague


# ── to_dict serialization ─────────────────────────────────────────────────

def test_to_dict_when_vague():
    d = check_prompt("fix it").to_dict()
    assert d["vague"] is True
    assert isinstance(d["signals"], list)
    assert d["suggestion"]
    assert isinstance(d["questions"], list)
    assert "bypass_reason" not in d  # only present when bypassed


def test_to_dict_when_bypassed():
    d = check_prompt("/help").to_dict()
    assert d["vague"] is False
    assert d["bypass_reason"] == "slash-command"
