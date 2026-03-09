"""Neurologist-specific commands: pulse, challenge, introspect.

Pulse provides system health overview. Challenge implements the corrigibility
skeptic protocol. Introspect asks each surgeon to self-report capabilities.
"""
from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from three_surgeons.core.models import LLMProvider, LLMResponse


@dataclass
class CheckDetail:
    """Single health check within a pulse scan."""

    ok: bool
    detail: str
    latency_ms: float = 0.0


@dataclass
class PulseResult:
    """Outcome of a neurologist pulse scan."""

    healthy: bool
    checks: Dict[str, CheckDetail]
    summary: str


@dataclass
class Challenge:
    """A single corrigibility challenge."""

    claim: str
    challenge: str
    severity: str  # critical | worth_testing | informational
    suggested_test: Optional[str] = None


@dataclass
class ChallengeResult:
    """Outcome of a neurologist challenge scan."""

    topic: str
    challenges: List[Challenge]
    raw_response: str


@dataclass
class IterativeChallengeResult:
    """Outcome of multi-round neurologist challenge."""

    topic: str
    challenges: List[Challenge]
    iteration_count: int
    per_round: List[List[Challenge]]


@dataclass
class IntrospectResult:
    """Self-report from a single surgeon."""

    model: str
    capabilities: str
    limitations: str
    latency_ms: float = 0.0
    ok: bool = True


def neurologist_pulse(
    neurologist: Any,
    state_backend: Any = None,
    evidence_store: Any = None,
    gpu_lock_path: Optional[str] = None,
) -> PulseResult:
    """Run a system health pulse check.

    Checks LLM health, state backend, evidence store, and GPU lock status.
    """
    checks: Dict[str, CheckDetail] = {}

    # Check LLM health
    t0 = time.monotonic()
    try:
        resp = neurologist.ping(timeout_s=5.0)
        latency = (time.monotonic() - t0) * 1000
        checks["llm_health"] = CheckDetail(
            ok=resp.ok,
            detail=f"Neurologist {'operational' if resp.ok else 'unhealthy'}",
            latency_ms=latency,
        )
    except Exception as exc:
        latency = (time.monotonic() - t0) * 1000
        checks["llm_health"] = CheckDetail(
            ok=False, detail=f"Neurologist unreachable: {exc}", latency_ms=latency
        )

    # Check state backend
    if state_backend is not None:
        t0 = time.monotonic()
        try:
            alive = state_backend.ping()
            latency = (time.monotonic() - t0) * 1000
            checks["state_backend"] = CheckDetail(
                ok=alive, detail="State backend operational" if alive else "State backend down", latency_ms=latency
            )
        except Exception as exc:
            latency = (time.monotonic() - t0) * 1000
            checks["state_backend"] = CheckDetail(
                ok=False, detail=f"State backend error: {exc}", latency_ms=latency
            )

    # Check evidence store
    if evidence_store is not None:
        t0 = time.monotonic()
        try:
            stats = evidence_store.get_stats()
            latency = (time.monotonic() - t0) * 1000
            checks["evidence_store"] = CheckDetail(
                ok=True, detail=f"Evidence store: {stats.get('total', 0)} learnings", latency_ms=latency
            )
        except Exception as exc:
            latency = (time.monotonic() - t0) * 1000
            checks["evidence_store"] = CheckDetail(
                ok=False, detail=f"Evidence store error: {exc}", latency_ms=latency
            )

    # Check GPU lock
    if gpu_lock_path is not None:
        try:
            if os.path.exists(gpu_lock_path):
                pid_str = open(gpu_lock_path).read().strip()
                if pid_str:
                    pid = int(pid_str)
                    try:
                        os.kill(pid, 0)
                        checks["gpu_lock"] = CheckDetail(ok=True, detail=f"GPU lock held by PID {pid} (alive)")
                    except OSError:
                        checks["gpu_lock"] = CheckDetail(ok=False, detail=f"GPU lock stale: PID {pid} dead")
                else:
                    checks["gpu_lock"] = CheckDetail(ok=False, detail="GPU lock file empty (stale)")
            else:
                checks["gpu_lock"] = CheckDetail(ok=True, detail="GPU lock free")
        except Exception as exc:
            checks["gpu_lock"] = CheckDetail(ok=False, detail=f"GPU lock check error: {exc}")

    healthy = all(c.ok for c in checks.values())
    failed = [name for name, c in checks.items() if not c.ok]
    if healthy:
        summary = f"All {len(checks)} checks healthy"
    else:
        summary = f"Unhealthy: {', '.join(failed)}"

    return PulseResult(healthy=healthy, checks=checks, summary=summary)


def neurologist_challenge(
    topic: str,
    neurologist: Any,
    evidence_store: Any = None,
    file_paths: Optional[List[str]] = None,
) -> ChallengeResult:
    """Run corrigibility skeptic challenge on a topic.

    Gathers evidence context if available, then asks the neurologist to
    challenge assumed-true aspects of the topic.
    """
    # Gather context
    context_parts: List[str] = []

    # File context
    if file_paths:
        file_contents: List[str] = []
        for fp in file_paths:
            try:
                with open(fp, "r") as f:
                    content = f.read()
                file_contents.append(f"--- {fp} ---\n{content}")
            except (OSError, IOError):
                continue
        if file_contents:
            context_parts.append("Relevant source files:")
            context_parts.extend(file_contents)

    if evidence_store is not None:
        try:
            results = evidence_store.search(topic, limit=5)
            if results:
                context_parts.append("Existing evidence:")
                for r in results:
                    context_parts.append(f"- {r.get('title', '')}: {r.get('content', '')[:200]}")
        except Exception:
            pass

    context = "\n".join(context_parts) if context_parts else ""

    system = (
        "You are a corrigibility skeptic. Your job is to challenge assumed-true "
        "aspects of the given topic. For each assumption you identify, provide a "
        "JSON array of objects with: claim (the assumption), challenge (why it might "
        "be wrong), severity (critical/worth_testing/informational), suggested_test "
        "(optional test to verify). Output ONLY the JSON array."
    )
    prompt = f"Topic: {topic}"
    if context:
        prompt += f"\n\nContext:\n{context}"

    try:
        resp = neurologist.query(system=system, prompt=prompt, max_tokens=2048, temperature=0.7)
        raw = resp.content if resp.ok else ""
    except Exception:
        raw = ""

    challenges = _parse_challenges(raw)
    return ChallengeResult(topic=topic, challenges=challenges, raw_response=raw)


def _parse_challenges(raw: str) -> List[Challenge]:
    """Parse JSON array of challenges from LLM response."""
    if not raw:
        return []
    try:
        # Try to extract JSON array from response
        text = raw.strip()
        # Find first [ and last ]
        start = text.find("[")
        end = text.rfind("]")
        if start >= 0 and end > start:
            text = text[start : end + 1]
        data = json.loads(text)
        if not isinstance(data, list):
            data = [data]
        results = []
        for item in data:
            if isinstance(item, dict):
                results.append(
                    Challenge(
                        claim=str(item.get("claim", "")),
                        challenge=str(item.get("challenge", "")),
                        severity=str(item.get("severity", "informational")),
                        suggested_test=item.get("suggested_test"),
                    )
                )
        return results if results else [Challenge(claim=raw[:200], challenge=raw, severity="informational")]
    except (json.JSONDecodeError, TypeError, ValueError):
        return [Challenge(claim=raw[:200], challenge=raw, severity="informational")]


def neurologist_challenge_iterative(
    topic: str,
    neurologist: Any,
    evidence_store: Any = None,
    file_paths: Optional[List[str]] = None,
    rounds: int = 1,
) -> IterativeChallengeResult:
    """Run iterative corrigibility challenge (2-3 rounds).

    Each round feeds prior challenges back to the neurologist for deeper probing.
    """
    all_challenges: List[Challenge] = []
    per_round: List[List[Challenge]] = []

    for i in range(rounds):
        if i == 0:
            result = neurologist_challenge(
                topic, neurologist,
                evidence_store=evidence_store,
                file_paths=file_paths,
            )
        else:
            # Build prompt with prior findings
            prior_text = "\n".join(
                f"- [{c.severity}] {c.claim}: {c.challenge}"
                for c in all_challenges
            )
            deeper_topic = (
                f"{topic}\n\n"
                f"Prior challenge findings (round {i}):\n{prior_text}\n\n"
                f"Dig deeper: what did the previous challenges MISS? "
                f"What second-order effects or hidden assumptions remain?"
            )
            result = neurologist_challenge(
                deeper_topic, neurologist,
                evidence_store=evidence_store,
                file_paths=file_paths,
            )

        per_round.append(result.challenges)
        all_challenges.extend(result.challenges)

    return IterativeChallengeResult(
        topic=topic,
        challenges=all_challenges,
        iteration_count=rounds,
        per_round=per_round,
    )


def introspect(providers: Dict[str, Any]) -> Dict[str, IntrospectResult]:
    """Ask each provider to self-report capabilities and limitations."""
    results: Dict[str, IntrospectResult] = {}

    system = "You are performing a self-assessment."
    prompt = (
        "Report your capabilities, limitations, and what you're best and worst at. "
        "Be concise (3-5 sentences)."
    )

    for name, provider in providers.items():
        t0 = time.monotonic()
        try:
            resp = provider.query(system=system, prompt=prompt, max_tokens=512, temperature=0.5)
            latency = (time.monotonic() - t0) * 1000
            if resp.ok:
                content = resp.content
                # Split into capabilities/limitations if possible
                results[name] = IntrospectResult(
                    model=resp.model,
                    capabilities=content,
                    limitations="",
                    latency_ms=latency,
                    ok=True,
                )
            else:
                results[name] = IntrospectResult(
                    model=resp.model,
                    capabilities="",
                    limitations=f"Error: {resp.content}",
                    latency_ms=latency,
                    ok=False,
                )
        except Exception as exc:
            latency = (time.monotonic() - t0) * 1000
            results[name] = IntrospectResult(
                model="unknown",
                capabilities="",
                limitations=f"Unreachable: {exc}",
                latency_ms=latency,
                ok=False,
            )

    return results
