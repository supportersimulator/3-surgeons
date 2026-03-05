"""Complexity Vector Sentinel — monitors project complexity across dimensions.

Each complexity vector has keywords, a risk score, and a noise threshold.
The sentinel scans content for keyword matches, computes a weighted risk
score, and escalates when thresholds are exceeded.

Extracted from complexity_vector_sentinel.py (559 lines). Simplified to
the core scanning/scoring logic without the full scheduler integration.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Dict, List, Optional

from three_surgeons.core.state import StateBackend


@dataclass
class ComplexityVector:
    """A single complexity dimension to monitor.

    Attributes:
        id: Unique identifier (e.g., "CV-001").
        name: Human-readable name (e.g., "Authentication complexity").
        keywords: Terms to search for in content.
        category: Classification: structural, operational, resource, or identity.
        risk_score: Severity weight 0.0-1.0.
        noise_threshold: Max keyword hits before vector is discarded as noise.
            Hits > this value are too noisy to be meaningful.
    """

    id: str
    name: str
    keywords: List[str]
    category: str = "operational"
    risk_score: float = 0.5
    noise_threshold: int = 6


@dataclass
class SentinelResult:
    """Outcome of a sentinel scan cycle.

    Attributes:
        vectors_checked: Total vectors evaluated.
        vectors_triggered: Vectors with keyword hits within noise threshold.
        risk_level: Aggregate risk: none/low/medium/high/critical.
        triggered_vectors: Details of each triggered vector.
        overall_score: Weighted average risk score (0.0-1.0).
        recommendations: Actionable suggestions based on triggered vectors.
    """

    vectors_checked: int
    vectors_triggered: int
    risk_level: str
    triggered_vectors: List[Dict]
    overall_score: float
    recommendations: List[str]


# ── Default Vectors ──────────────────────────────────────────────────

DEFAULT_VECTORS: List[ComplexityVector] = [
    ComplexityVector(
        id="CV-001", name="Authentication complexity",
        keywords=["auth", "token", "jwt", "oauth", "session"],
        category="structural", risk_score=0.7,
    ),
    ComplexityVector(
        id="CV-002", name="Database schema changes",
        keywords=["migration", "schema", "alter table", "index"],
        category="structural", risk_score=0.6,
    ),
    ComplexityVector(
        id="CV-003", name="API surface changes",
        keywords=["endpoint", "route", "api", "rest", "graphql"],
        category="operational", risk_score=0.5,
    ),
    ComplexityVector(
        id="CV-004", name="Security concerns",
        keywords=["injection", "xss", "csrf", "vulnerability", "exploit"],
        category="structural", risk_score=0.9,
    ),
    ComplexityVector(
        id="CV-005", name="Performance impact",
        keywords=["cache", "latency", "throughput", "bottleneck", "n+1"],
        category="resource", risk_score=0.6,
    ),
    ComplexityVector(
        id="CV-006", name="Concurrency issues",
        keywords=["lock", "mutex", "race condition", "deadlock", "thread"],
        category="resource", risk_score=0.8,
    ),
    ComplexityVector(
        id="CV-007", name="External dependencies",
        keywords=["api key", "third-party", "vendor", "sdk", "external"],
        category="operational", risk_score=0.5,
    ),
    ComplexityVector(
        id="CV-008", name="State management",
        keywords=["state", "redux", "context", "global", "singleton"],
        category="operational", risk_score=0.4,
    ),
    ComplexityVector(
        id="CV-009", name="Redundant agents",
        keywords=["agent", "duplicate", "overlap", "redundant"],
        category="structural", risk_score=0.6,
    ),
    ComplexityVector(
        id="CV-010", name="Container name variants",
        keywords=["container", "docker", "naming", "alias"],
        category="identity", risk_score=0.5,
    ),
    ComplexityVector(
        id="CV-011", name="API domain sprawl",
        keywords=["api", "endpoint", "domain", "route", "sprawl"],
        category="operational", risk_score=0.65,
    ),
    ComplexityVector(
        id="CV-012", name="Action fragmentation",
        keywords=["action", "handler", "dispatch", "fragment"],
        category="structural", risk_score=0.55,
    ),
    ComplexityVector(
        id="CV-013", name="Identity alias confusion",
        keywords=["alias", "rename", "identity", "mapping"],
        category="identity", risk_score=0.6,
    ),
    ComplexityVector(
        id="CV-014", name="Message broker complexity",
        keywords=["queue", "broker", "pubsub", "event bus"],
        category="operational", risk_score=0.7,
    ),
    ComplexityVector(
        id="CV-015", name="Scheduler proliferation",
        keywords=["scheduler", "cron", "timer", "job", "interval"],
        category="resource", risk_score=0.65,
    ),
    ComplexityVector(
        id="CV-ES", name="Error swallowing",
        keywords=["except", "pass", "silent", "ignore", "swallow"],
        category="operational", risk_score=0.8,
    ),
    ComplexityVector(
        id="CV-TSD", name="Temporal state drift",
        keywords=["stale", "expired", "drift", "sync", "clock"],
        category="operational", risk_score=0.75,
    ),
    ComplexityVector(
        id="CV-FLC", name="Feedback loop contamination",
        keywords=["feedback", "loop", "circular", "recursive", "self-reference"],
        category="structural", risk_score=0.85,
    ),
    ComplexityVector(
        id="CV-PVS", name="Python version skew",
        keywords=["version", "compat", "deprecated", "legacy", "python"],
        category="operational", risk_score=0.55,
    ),
    ComplexityVector(
        id="CV-SCC", name="SQLite connection chaos",
        keywords=["sqlite", "connection", "lock", "concurrent", "wal"],
        category="resource", risk_score=0.7,
    ),
]


def _score_to_risk_level(score: float) -> str:
    """Map a 0.0-1.0 score to a risk level string."""
    if score == 0.0:
        return "none"
    if score < 0.2:
        return "low"
    if score < 0.5:
        return "medium"
    if score < 0.8:
        return "high"
    return "critical"


def _count_keyword_hits(content_lower: str, keywords: List[str]) -> int:
    """Count total keyword occurrences in lowercased content."""
    total = 0
    for kw in keywords:
        kw_lower = kw.lower()
        # Use regex word-boundary-aware search for single words,
        # plain count for multi-word phrases.
        if " " in kw_lower:
            total += content_lower.count(kw_lower)
        else:
            total += len(re.findall(r"\b" + re.escape(kw_lower) + r"\b", content_lower))
    return total


class Sentinel:
    """Monitors project complexity across configurable vectors.

    Scans content for keyword matches, applies noise gating, and
    computes a weighted risk score. Optionally persists scan history
    to a StateBackend.
    """

    def __init__(
        self,
        vectors: Optional[List[ComplexityVector]] = None,
        state: Optional[StateBackend] = None,
    ) -> None:
        self._vectors: List[ComplexityVector] = vectors if vectors is not None else list(DEFAULT_VECTORS)
        self._state = state

    def run_cycle(self, content: str) -> SentinelResult:
        """Scan content against all vectors and return a SentinelResult.

        For each vector:
        1. Count keyword hits in content (case-insensitive).
        2. If hits > 0 and hits <= noise_threshold: vector triggered.
        3. If hits > noise_threshold: discarded (too noisy).

        Overall score = weighted average of triggered vectors' risk_scores.
        Risk level derived from overall score.
        """
        content_lower = content.lower()
        triggered: List[Dict] = []

        for vec in self._vectors:
            hits = _count_keyword_hits(content_lower, vec.keywords)
            if hits > 0 and hits <= vec.noise_threshold:
                triggered.append({
                    "id": vec.id,
                    "name": vec.name,
                    "hits": hits,
                    "risk_score": vec.risk_score,
                })

        # Compute weighted average score
        if triggered:
            overall_score = sum(t["risk_score"] for t in triggered) / len(triggered)
        else:
            overall_score = 0.0

        risk_level = _score_to_risk_level(overall_score)

        # Generate recommendations for triggered vectors
        recommendations = _build_recommendations(triggered)

        return SentinelResult(
            vectors_checked=len(self._vectors),
            vectors_triggered=len(triggered),
            risk_level=risk_level,
            triggered_vectors=triggered,
            overall_score=overall_score,
            recommendations=recommendations,
        )


def _build_recommendations(triggered: List[Dict]) -> List[str]:
    """Generate actionable recommendations from triggered vectors."""
    recs: List[str] = []
    for t in triggered:
        score = t["risk_score"]
        name = t["name"]
        if score >= 0.8:
            recs.append(f"High {name.lower()} detected -- consider cross-examination")
        elif score >= 0.5:
            recs.append(f"Elevated {name.lower()} -- review before proceeding")
        else:
            recs.append(f"Minor {name.lower()} noted -- monitor")
    return recs
