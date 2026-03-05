"""Direct query commands and dissent testing protocol.

ask_local/ask_remote provide thin wrappers for direct surgeon access.
test_dissent and resolve_disagreement implement the steelmanning protocol
for handling inter-surgeon disagreements.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class DissentResult:
    """Outcome of testing a dissenting view through steelmanning."""

    topic: str
    steelmanned_argument: str
    counter_evidence: List[str]
    verdict: str  # dissent_valid | dissent_partially_valid | dissent_unfounded
    confidence: float
    raw_response: str


def ask_local(
    prompt: str,
    neurologist: Any,
    system_prompt: Optional[str] = None,
) -> Any:
    """Direct query to the neurologist (local model).

    Returns the raw LLMResponse from the provider.
    """
    system = system_prompt or "You are a helpful local AI assistant. Be concise."
    return neurologist.query(system=system, prompt=prompt, max_tokens=2048, temperature=0.7)


def ask_remote(
    prompt: str,
    cardiologist: Any,
    system_prompt: Optional[str] = None,
) -> Any:
    """Direct query to the cardiologist (remote model).

    Returns the raw LLMResponse from the provider.
    """
    system = system_prompt or "You are a helpful AI assistant providing external perspective. Be concise."
    return cardiologist.query(system=system, prompt=prompt, max_tokens=2048, temperature=0.7)


def test_dissent(
    topic: str,
    dissenting_view: str,
    provider: Any,
    original_claim: Optional[str] = None,
) -> DissentResult:
    """Test a dissenting view through steelmanning.

    Asks the provider to make the strongest possible case for the dissent,
    then evaluate whether it has merit.
    """
    system = (
        "You are testing a dissenting view through steelmanning. Given the topic "
        "and a dissenting opinion, make the STRONGEST possible case for the dissent "
        "being correct. Then evaluate whether the dissent has merit. Output JSON with: "
        "steelmanned_argument (string), counter_evidence (list of strings), "
        "verdict (dissent_valid|dissent_partially_valid|dissent_unfounded), "
        "confidence (0.0-1.0)."
    )
    prompt_parts = [f"Topic: {topic}", f"Dissenting view: {dissenting_view}"]
    if original_claim:
        prompt_parts.append(f"Original claim: {original_claim}")
    prompt = "\n".join(prompt_parts)

    try:
        resp = provider.query(system=system, prompt=prompt, max_tokens=2048, temperature=0.5)
        raw = resp.content if resp.ok else ""
    except Exception:
        raw = ""

    return _parse_dissent(topic, raw)


def _parse_dissent(topic: str, raw: str) -> DissentResult:
    """Parse a dissent result from LLM JSON response."""
    if not raw:
        return DissentResult(
            topic=topic,
            steelmanned_argument="",
            counter_evidence=[],
            verdict="dissent_partially_valid",
            confidence=0.5,
            raw_response=raw,
        )
    try:
        # Try to extract JSON from response
        text = raw.strip()
        start = text.find("{")
        end = text.rfind("}")
        if start >= 0 and end > start:
            text = text[start : end + 1]
        data = json.loads(text)
        return DissentResult(
            topic=topic,
            steelmanned_argument=str(data.get("steelmanned_argument", "")),
            counter_evidence=list(data.get("counter_evidence", [])),
            verdict=str(data.get("verdict", "dissent_partially_valid")),
            confidence=float(data.get("confidence", 0.5)),
            raw_response=raw,
        )
    except (json.JSONDecodeError, TypeError, ValueError):
        return DissentResult(
            topic=topic,
            steelmanned_argument=raw[:500],
            counter_evidence=[],
            verdict="dissent_partially_valid",
            confidence=0.5,
            raw_response=raw,
        )


def resolve_disagreement(
    topic: str,
    opinions: Dict[str, str],
    arbiter: Any,
) -> DissentResult:
    """Resolve a disagreement by testing the minority view.

    Finds the minority opinion (if any) and steelmans it through the arbiter.
    If all opinions are the same, tests whether the unanimous view could be wrong.
    """
    # Find majority and minority
    from collections import Counter

    counts = Counter(opinions.values())
    if len(counts) <= 1:
        # All agree — test whether the unanimous view could be wrong
        unanimous = list(opinions.values())[0]
        return test_dissent(
            topic=topic,
            dissenting_view=f"The unanimous agreement '{unanimous}' may be wrong",
            provider=arbiter,
            original_claim=unanimous,
        )

    # Find minority view
    majority_view = counts.most_common(1)[0][0]
    minority_views = [v for v in opinions.values() if v != majority_view]
    minority_view = minority_views[0]

    return test_dissent(
        topic=topic,
        dissenting_view=minority_view,
        provider=arbiter,
        original_claim=majority_view,
    )
