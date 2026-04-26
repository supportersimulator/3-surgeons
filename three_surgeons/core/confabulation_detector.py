"""Confabulation detector for surgeon outputs.

Catches regressions where surgeon (e.g. surgeon-reviewer subagent) hallucinates
unrelated content -- e.g. answering a webhook question with kernel PM callbacks
or fabricated kernel parameter baselines.

Heuristics:
  1. Out-of-domain term injection -- the answer references concepts whose
     domain is incompatible with the question's domain.
  2. Fabricated technical jargon -- a regex hit-list of phrases that have
     historically appeared in confabulated 3-surgeons outputs.
  3. Citation-style claims without basis -- "according to spec X" / "per the
     Linux kernel docs" when the question mentioned no such spec/source.

Returns a :class:`ConfabulationReport`. Confidence > 0.5 should be treated as
flagged; pipelines should surface a warning and increment a counter.

Pure-Python, no LLM calls -- safe to run on every surgeon response.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Iterable, List, Optional, Set


# ── Domain ontology ──────────────────────────────────────────────────
#
# Each domain has trigger terms (when present in the QUESTION, the question
# is considered to be IN that domain) and signature terms (when present in
# the ANSWER, the answer is considered to be IN that domain).
#
# A confabulation is suspected when an answer's signature domain is disjoint
# from any of the question's trigger domains.

_DOMAINS: dict[str, dict[str, List[str]]] = {
    "kernel": {
        "trigger": [
            "linux kernel", "kernel module", "syscall", "kthread",
            "device driver", "interrupt handler", "drm", "drm driver",
        ],
        "signature": [
            "kernel pm", "pm callbacks", "pm domain", "kernel callbacks",
            "syscall hook", "syscall hooks", "kernel param", "kernel parameter",
            "kthread", "ioctl", "/proc/", "/sys/kernel", "drm_dev_",
            "module_param", "EXPORT_SYMBOL", "request_irq", "kmalloc",
            "spin_lock", "rcu_read_lock", "schedule_timeout",
        ],
    },
    "webhook": {
        "trigger": [
            "webhook", "http callback", "x-hub-signature", "payload url",
            "context dna webhook", "webhook fix",
        ],
        "signature": [
            "webhook", "http post", "payload", "x-hub-signature",
            "callback url", "endpoint", "retry policy", "200 ok",
            "signature header", "hmac",
        ],
    },
    "audio": {
        "trigger": ["audio", "_ecg", "ecg waveform", "soundscape", "buffer underrun"],
        "signature": ["audio", "_ecg", "wav", "sample rate", "buffer", "playback"],
    },
    "git": {
        "trigger": ["git", "commit", "branch", "merge", "pull request", "rebase"],
        "signature": ["git", "commit", "branch", "merge", "rebase", "submodule"],
    },
    "llm": {
        "trigger": [
            "llm", "openai", "anthropic", "deepseek", "claude", "qwen",
            "model fallback", "cardiologist", "neurologist",
        ],
        "signature": [
            "llm", "openai", "anthropic", "deepseek", "claude", "qwen",
            "fallback", "provider",
        ],
    },
}


# ── Fabricated jargon hit-list ───────────────────────────────────────
#
# Phrases that have historically appeared in 3-surgeons confabulations.
# Lowercased substring or compiled regex match. Add new entries as
# regressions are observed.
_FABRICATED_JARGON = (
    re.compile(r"\bkernel\s+pm\b", re.IGNORECASE),
    re.compile(r"\bpm\s+(callback|domain)s?\b", re.IGNORECASE),
    re.compile(r"\bkernel\s+(callback|param|parameter)s?\b", re.IGNORECASE),
    re.compile(r"\bsyscall\s+hooks?\b", re.IGNORECASE),
    re.compile(r"\bkernel\s+param(eter)?\s+baseline\b", re.IGNORECASE),
    re.compile(r"\bkthread\s+scheduler\b", re.IGNORECASE),
    re.compile(r"\bdrm\s+(driver|callbacks?)\b", re.IGNORECASE),
    re.compile(r"\b/sys/kernel/[A-Za-z0-9_/]+", re.IGNORECASE),
    re.compile(r"\bmodule_param\s*\(", re.IGNORECASE),
    re.compile(r"\bEXPORT_SYMBOL\s*\(", re.IGNORECASE),
)


# ── Citation pattern ─────────────────────────────────────────────────
#
# Matches "according to ...", "per the ... spec", "[RFC ####]" etc. When
# the cited source name is not present in the question, this is suspicious.
_CITATION_PATTERN = re.compile(
    r"\b(?:according to|per the|as defined in|see the|in the)\s+"
    r"([A-Z][A-Za-z0-9 _\-/.]{2,40}?\s+(?:spec(?:ification)?|"
    r"standard|RFC|docs?|documentation|manual|guide|paper))",
    re.IGNORECASE,
)
_RFC_PATTERN = re.compile(r"\bRFC\s*\d{3,5}\b", re.IGNORECASE)


# ── Public API ───────────────────────────────────────────────────────


@dataclass
class ConfabulationReport:
    """Result of running a surgeon answer through the detector.

    confidence: 0.0 = clean, 1.0 = certain confabulation. > 0.5 should be
    treated as flagged by callers.
    """

    confabulated: bool
    signals: List[str] = field(default_factory=list)
    confidence: float = 0.0

    def to_dict(self) -> dict:
        return {
            "confabulated": self.confabulated,
            "signals": list(self.signals),
            "confidence": round(self.confidence, 3),
        }


def detect_confabulation(question: str, answer: str) -> ConfabulationReport:
    """Heuristically detect confabulation in a surgeon answer.

    Returns ConfabulationReport with confidence in [0.0, 1.0]. A score above
    0.5 indicates the answer should be flagged for human review.

    The detector is intentionally conservative: it errs on the side of
    flagging rather than missing regressions. False positives are cheaper
    than silent confabulation.
    """
    if not answer or not answer.strip():
        return ConfabulationReport(confabulated=False, signals=[], confidence=0.0)

    q_lower = (question or "").lower()
    a_lower = answer.lower()

    signals: List[str] = []
    score = 0.0

    # 1. Out-of-domain term injection ────────────────────────────────
    question_domains = _domains_present(q_lower, "trigger")
    answer_domains = _domains_present(a_lower, "signature")

    if question_domains and answer_domains:
        foreign = answer_domains - question_domains
        for d in sorted(foreign):
            signals.append(f"out_of_domain:{d}")
            # Kernel-shaped foreign content is the signature regression
            # (the documented kernel-PM hallucination). Weight it heavier.
            score += 0.45 if d == "kernel" else 0.25

    # 2. Fabricated jargon hit-list ──────────────────────────────────
    for pattern in _FABRICATED_JARGON:
        m = pattern.search(answer)
        if m and m.group(0).lower() not in q_lower:
            signals.append(f"fabricated_jargon:{m.group(0).strip().lower()}")
            score += 0.35

    # 3. Citation-style claims without basis ─────────────────────────
    for m in _CITATION_PATTERN.finditer(answer):
        cited = m.group(1).strip().lower()
        # Strip the trailing noun ("spec"/"docs"/...) for question lookup
        head = re.sub(
            r"\s+(spec(?:ification)?|standard|rfc|docs?|documentation|"
            r"manual|guide|paper)$",
            "",
            cited,
        ).strip()
        if head and head not in q_lower:
            signals.append(f"unbacked_citation:{cited}")
            score += 0.2

    for m in _RFC_PATTERN.finditer(answer):
        rfc = m.group(0).lower()
        if rfc not in q_lower:
            signals.append(f"unbacked_citation:{rfc}")
            score += 0.2

    # Clamp ──────────────────────────────────────────────────────────
    if score > 1.0:
        score = 1.0

    return ConfabulationReport(
        confabulated=score > 0.5,
        signals=signals,
        confidence=score,
    )


# ── Helpers ──────────────────────────────────────────────────────────


def _domains_present(text: str, key: str) -> Set[str]:
    """Return domain names whose `key` term list appears in `text`."""
    found: Set[str] = set()
    for name, terms in _DOMAINS.items():
        for term in terms.get(key, ()):
            if term in text:
                found.add(name)
                break
    return found


def known_domains() -> Iterable[str]:
    """Public introspection helper -- list registered domains."""
    return tuple(_DOMAINS.keys())
