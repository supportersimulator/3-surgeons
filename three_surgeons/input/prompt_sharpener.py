"""Deterministic vague-prompt detector for the surgeons' input layer.

Ported from IJFW's ``mcp-server/src/prompt-check.js`` (commit per harvest plan
2026-04-25). Pure regex, no LLM, no I/O — safe to call in any code path
(``ask_local`` handler, MCP tool entry, hook script, IDE pre-submit).

WHY THIS EXISTS
---------------
3-Surgeons cycles are expensive — each consult/cross-exam burns external API
budget and Atlas context. A vague prompt like "fix this" or "make it better"
without a target wastes those cycles.

This module catches vague prompts BEFORE the surgeons engage and surfaces
≤3 clarifying questions so the user/agent can sharpen the request first.

DESIGN
------
* 7-rule vagueness taxonomy (bare verb, anaphora, abstract goal,
  no_target, scope_plural, polysemous, missing_constraint).
* Fires only when ``signals >= 2 AND prompt < 30 tokens AND no_target``.
  Single-signal trips are silent — keeps false-positive rate low.
* Bypasses for: empty input, ``*`` prefix, slash-commands, ``#`` memorize
  prefix, ``3s off`` override keyword, very long prompts (>4 KB), fenced
  code blocks (assumed user already knows the target).
* Suggestions use *positive framing* — never says "your prompt is vague";
  says "Sharpening your aim — which file/function/symbol?".
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Callable, Final


# ── Vagueness rules (deterministic, regex-only) ──────────────────────────


def _rule_bare_verb(text: str) -> bool:
    t = text.strip().lower()
    tokens = t.split()
    if len(tokens) >= 6:
        return False
    return bool(re.match(
        r"^(fix|refactor|improve|clean\s*up|optimi[sz]e|update|review|"
        r"check|test|debug|analy[sz]e|handle|sort\s*out|tidy)\b",
        t,
    ))


def _rule_unresolved_anaphora(text: str) -> bool:
    return bool(re.match(
        r"^(this|that|it|these|those|"
        r"the\s+(bug|issue|file|code|function|error|problem))\b",
        text.strip(),
        re.IGNORECASE,
    ))


def _rule_abstract_goal(text: str) -> bool:
    has_abstract = re.search(
        r"\b(better|cleaner|nicer|more\s+robust|production[\s-]?ready|"
        r"proper|correct|good|nice|right)\b",
        text, re.IGNORECASE,
    )
    if not has_abstract:
        return False
    has_metric = re.search(
        r"\d+\s*(ms|%|x|kb|mb|sec|s\b|tests?\b|users?\b)",
        text, re.IGNORECASE,
    )
    has_path = re.search(
        r"[\w./-]+\.\w{1,5}(\b|:)|src/|tests?/", text, re.IGNORECASE,
    )
    return not (has_metric or has_path)


def _rule_no_target(text: str) -> bool:
    if re.search(r"[\w./-]+\.\w{1,5}(\b|:)", text):
        return False  # file path
    if re.search(r":\d+", text):
        return False  # line number
    if re.search(r"\b(src|lib|app|tests?|spec|docs?)/", text, re.IGNORECASE):
        return False  # dir prefix
    # Identifier: snake_case, UpperCamelCase, lowerCamelCase (>=2 segments)
    if re.search(
        r"\b([a-z]+_[a-z][\w_]*|[A-Z][a-z]+[A-Z]\w*|[a-z]+[A-Z]\w*)\b",
        text,
    ):
        return False
    return True


def _rule_scope_plural(text: str) -> bool:
    return bool(re.search(
        r"\b(the\s+tests|all\s+the\s+(things|stuff|files)|"
        r"everything|stuff|things)\b",
        text, re.IGNORECASE,
    ))


def _rule_polysemous(text: str) -> bool:
    t = text.strip().lower()
    return bool(re.match(
        r"^(source|build|run|deploy|ship|release|setup|set\s*up)\.?\s*$", t,
    ))


def _rule_missing_constraint(text: str) -> bool:
    if len(text.strip().split()) < 4:
        return False
    has_constraint = re.search(
        r"\b(must|should|when|if|until|without|only|always|never|except)\b",
        text, re.IGNORECASE,
    )
    has_number = re.search(r"\b\d+\b", text)
    return not (has_constraint or has_number)


_RULES: Final[list[tuple[str, Callable[[str], bool]]]] = [
    ("bare_verb", _rule_bare_verb),
    ("unresolved_anaphora", _rule_unresolved_anaphora),
    ("abstract_goal", _rule_abstract_goal),
    ("no_target", _rule_no_target),
    ("scope_plural", _rule_scope_plural),
    ("polysemous", _rule_polysemous),
    ("missing_constraint", _rule_missing_constraint),
]


# ── Bypass conditions ─────────────────────────────────────────────────────


def _bypass_reason(text: object) -> str | None:
    if not isinstance(text, str):
        return "non-string"
    t = text.strip()
    if not t:
        return "empty"
    if t.startswith("*"):
        return "asterisk-prefix"
    if t.startswith("/"):
        return "slash-command"
    if t.startswith("#"):
        return "memorize-prefix"
    if re.search(r"\b3s\s+off\b", t, re.IGNORECASE):
        return "override-keyword"
    if len(t) > 4000:
        return "long-prompt"
    if re.search(r"^```", t, re.MULTILINE):
        return "fenced-code"
    return None


# ── Question pack builder ─────────────────────────────────────────────────


def _build_question_pack(signals: list[str]) -> list[str]:
    """Map signals → ≤3 clarifying questions (deduped)."""
    questions: list[str] = []
    seen: set[str] = set()

    def add(q: str) -> None:
        if q not in seen:
            seen.add(q)
            questions.append(q)

    for sig in signals:
        if len(questions) >= 3:
            break
        if sig in ("bare_verb", "no_target"):
            add("Which file, function, or line number is the target?")
        elif sig == "unresolved_anaphora":
            add("What does \"this/that\" refer to — a file, a symptom, "
                "or a prior message?")
        elif sig == "abstract_goal":
            add("What measurable outcome would mean this is done? "
                "(perf number, test passing, behaviour change)")
        elif sig == "scope_plural":
            add("Which specific items in the set — or do you mean "
                "the whole set?")
        elif sig == "polysemous":
            add("Which sense of that word — the build step, the source dir, "
                "the deploy target?")
        elif sig == "missing_constraint":
            add("Are there constraints I should know — must/should/never, "
                "deadlines, version pins?")
    return questions


# ── Public API ────────────────────────────────────────────────────────────


@dataclass
class SharpeningResult:
    vague: bool
    signals: list[str] = field(default_factory=list)
    suggestion: str = ""
    questions: list[str] = field(default_factory=list)
    bypass_reason: str | None = None

    def to_dict(self) -> dict:
        out: dict = {
            "vague": self.vague,
            "signals": list(self.signals),
            "suggestion": self.suggestion,
            "questions": list(self.questions),
        }
        if self.bypass_reason is not None:
            out["bypass_reason"] = self.bypass_reason
        return out


def check_prompt(text: object) -> SharpeningResult:
    """Return a :class:`SharpeningResult` for ``text``.

    Defensive: non-string input → ``vague=False`` with bypass_reason.
    Never raises (each rule wrapped in try/except so a bad regex can't
    break a hook).
    """
    bypass = _bypass_reason(text)
    if bypass is not None:
        return SharpeningResult(vague=False, bypass_reason=bypass)

    assert isinstance(text, str)  # narrowed by _bypass_reason

    signals: list[str] = []
    for rule_id, rule_fn in _RULES:
        try:
            if rule_fn(text):
                signals.append(rule_id)
        except Exception:  # noqa: BLE001 — never break the hook
            continue

    tokens = text.strip().split()
    short = len(tokens) < 30
    no_target = "no_target" in signals
    vague = (len(signals) >= 2) and short and no_target

    suggestion = ""
    questions: list[str] = []
    if vague:
        if "bare_verb" in signals and no_target:
            suggestion = (
                "Sharpening your aim — which file, function, or symbol? "
                "(e.g. src/auth.py:145, getUserById, the failing test name)"
            )
        elif "unresolved_anaphora" in signals:
            suggestion = (
                "Anchoring the reference — which file or recent code "
                "do you mean?"
            )
        else:
            suggestion = (
                "Pinning the target — naming the file, symbol, or expected "
                "behaviour will sharpen the edit."
            )
        questions = _build_question_pack(signals)

    return SharpeningResult(
        vague=vague,
        signals=signals,
        suggestion=suggestion,
        questions=questions,
    )


__all__ = ["check_prompt", "SharpeningResult"]
