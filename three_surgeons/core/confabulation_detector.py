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

RACE Q2 expansion: added orchestration / fleet / NATS / election ontologies and
a broader fabricated-jargon hit-list (ghost agents, rollback paradox, made-up
version pins, cross-contamination chains, etc.) based on observed surgeon
hallucinations in fleet coordination conversations.
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
    # ── RACE Q2: fleet / orchestration domains ──────────────────────
    "orchestration": {
        "trigger": [
            "orchestrat", "task queue", "agent runner",
            "agent pool", "subagent", "background agent", "worker pool",
            "claude code session",
        ],
        "signature": [
            "orchestrat", "task queue", "agent runner",
            "agent pool", "subagent", "worker pool", "task dispatch",
        ],
    },
    "fleet": {
        "trigger": [
            "fleet", "multi-fleet", "multifleet", "fleet daemon",
            "fleet-msg", "fleet message", "node id", "mac1", "mac2",
            "mac3", "chief relay", "fleet inbox", "fleet check",
            "fleet-check.sh",
        ],
        "signature": [
            "fleet", "multifleet", "node id", "chief relay", "seed file",
            "wake-on-lan", "fleet daemon", "fleet-msg",
        ],
    },
    "nats": {
        "trigger": [
            "nats", "jetstream", "nats subject", "nats subscription",
            "pub/sub", "publish/subscribe", "message bus", "fleet_nerve_nats",
        ],
        "signature": [
            "nats", "jetstream", "subject hierarchy", "subscription",
            "publish", "subscribe", "message bus",
        ],
    },
    "election": {
        "trigger": [
            "election", "leader election", "raft", "paxos", "quorum",
            "consensus protocol", "leader lease", "split brain",
        ],
        "signature": [
            "election", "leader election", "raft", "paxos", "quorum",
            "leader lease", "split brain", "term number",
        ],
    },
}


# ── Fabricated jargon hit-list ───────────────────────────────────────
#
# Phrases that have historically appeared in 3-surgeons confabulations.
# Lowercased substring or compiled regex match. Add new entries as
# regressions are observed.
_FABRICATED_JARGON = (
    # Original kernel/PM/syscall hallucinations (RACE M2)
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
    # ── RACE Q2: fictional fleet / orchestration infrastructure terms ──
    re.compile(r"\bghost\s+agents?\b", re.IGNORECASE),
    re.compile(r"\bghost\s+subscriptions?\b", re.IGNORECASE),
    re.compile(r"\bghost\s+process(?:es)?\b", re.IGNORECASE),
    # ── RACE Q2: made-up dependency chains ──────────────────────────
    re.compile(r"\brollback\s+paradox\b", re.IGNORECASE),
    re.compile(r"\bcross[- ]contamination\s+chain\b", re.IGNORECASE),
    # ── RACE Q2: jargon used without definitional context ──────────
    # NB: "circuit breaker" and "data plane / control plane" can be
    # legitimate. They are scored in `detect_confabulation` only when
    # the question never introduced them and no explanatory verb is
    # nearby. The patterns are lifted out so the detector can apply
    # context-sensitive rules.
    # ── RACE Q2: spurious version pins ──────────────────────────────
    # `pre-X.Y bug`, `pre-X.Y.Z release`, `post-X.Y release`.
    re.compile(r"\bpre-\d+(?:\.\d+){1,2}\s+(?:bug|regression|issue|fix)\b", re.IGNORECASE),
    re.compile(r"\bpost-\d+(?:\.\d+){1,2}\s+(?:release|change|behaviour|behavior)\b", re.IGNORECASE),
)


# Patterns that need context-sensitive evaluation. They are NOT added to
# `_FABRICATED_JARGON` because legitimate uses are common; instead
# `detect_confabulation` checks them only when guard conditions hold.
_CONTEXT_SENSITIVE_JARGON: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("circuit_breaker", re.compile(r"\bcircuit\s+breakers?\b", re.IGNORECASE)),
    ("data_plane", re.compile(r"\bdata\s+plane\b", re.IGNORECASE)),
    ("control_plane", re.compile(r"\bcontrol\s+plane\b", re.IGNORECASE)),
)

# When the question is clearly about userspace concerns and the answer
# starts blaming "the kernel", that's a confabulation pattern observed in
# real sessions (surgeon reaches for kernel-level explanations to look
# authoritative).
_USERSPACE_TRIGGERS = (
    "userspace", "user space", "python", "node.js", "javascript",
    "shell script", "bash", "zsh", "subprocess", "cli tool",
    "http request", "rest api", "webhook", "fleet-msg",
)
_KERNEL_BLAME_PATTERN = re.compile(
    r"\bthe\s+kernel\b(?!\s+(?:module|param|parameter|panic|of|trick|of\s+truth))",
    re.IGNORECASE,
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

# RACE Q2: bare "per the spec" / "per the docs" / "per the standard" with
# no source name at all is an unbacked-citation tell.
_BARE_CITATION_PATTERN = re.compile(
    r"\bper\s+the\s+(spec(?:ification)?|standard|docs?|documentation)\b",
    re.IGNORECASE,
)


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

    # 2b. Context-sensitive jargon ──────────────────────────────────
    # Flag jargon used as a confident-sounding noun when the question
    # never named it AND the answer doesn't introduce it (no defining
    # verb like "is a", "is the", "means", "refers to" nearby). The
    # question check is done on the singular form so "circuit breaker"
    # in the question covers "circuit breakers" in the answer.
    for label, pattern in _CONTEXT_SENSITIVE_JARGON:
        m = pattern.search(answer)
        if not m:
            continue
        if _phrase_in_question(label, q_lower):
            continue
        if _has_defining_context(answer, m):
            continue
        signals.append(f"unexplained_jargon:{label}")
        score += 0.2

    # 2c. "the kernel" blame in a userspace question ────────────────
    if any(t in q_lower for t in _USERSPACE_TRIGGERS) and "kernel" not in q_lower:
        if _KERNEL_BLAME_PATTERN.search(answer):
            signals.append("kernel_blame_in_userspace_question")
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

    # 3b. Bare "per the spec" with no named source ───────────────────
    for m in _BARE_CITATION_PATTERN.finditer(answer):
        if m.group(0).lower() not in q_lower:
            signals.append(f"unbacked_citation:bare_{m.group(1).lower()}")
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


def _has_defining_context(answer: str, match: re.Match[str]) -> bool:
    """Return True if a defining/explanatory verb sits within ~50 chars
    of the match — indicates the answer is introducing the term rather
    than wielding it as if pre-known.
    """
    start = max(0, match.start() - 50)
    end = min(len(answer), match.end() + 50)
    window = answer[start:end].lower()
    for marker in (
        " is a ", " is an ", " is the ", " are the ", " means ",
        " refers to ", " defined as ", " — a ", " - a ", " (a ",
        " (an ", "i.e.", "e.g.",
        "what is", "what's a", "how does", "what does",
    ):
        if marker in window:
            return True
    return False


# Map context-sensitive jargon labels back to the canonical question
# phrase to look for. Plural / singular variations of the same term
# in the answer should still count as "named in the question" if any
# of the variants appears.
_CTX_JARGON_QUESTION_VARIANTS: dict[str, tuple[str, ...]] = {
    "circuit_breaker": ("circuit breaker", "circuit breakers"),
    "data_plane": ("data plane", "data planes"),
    "control_plane": ("control plane", "control planes"),
}


def _phrase_in_question(label: str, q_lower: str) -> bool:
    for variant in _CTX_JARGON_QUESTION_VARIANTS.get(label, ()):
        if variant in q_lower:
            return True
    return False


def known_domains() -> Iterable[str]:
    """Public introspection helper -- list registered domains."""
    return tuple(_DOMAINS.keys())
