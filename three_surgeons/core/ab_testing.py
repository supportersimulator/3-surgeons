"""Autonomous A/B testing engine with safety constraints.

Full lifecycle management for experiments: propose, grace period, activate,
measure, conclude -- with strict guardrails preventing tests on safety-critical
parameters and auto-reverting experiments that exceed cost or duration limits.
"""
from __future__ import annotations

import json
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional

from three_surgeons.core.config import Config
from three_surgeons.core.evidence import EvidenceStore
from three_surgeons.core.state import StateBackend


class TestStatus(Enum):
    """Lifecycle states for an autonomous A/B test."""

    PROPOSED = "proposed"
    GRACE_PERIOD = "grace_period"
    ACTIVE = "active"
    MONITORING = "monitoring"
    CONCLUDED = "concluded"
    VETOED = "vetoed"
    REVERTED = "reverted"


# Terminal states: tests in these states are no longer "active".
_TERMINAL_STATUSES = {TestStatus.CONCLUDED, TestStatus.VETOED, TestStatus.REVERTED}


@dataclass
class AutonomousTest:
    """A single A/B experiment with safety metadata."""

    id: str
    param: str
    variant_a: str
    variant_b: str
    hypothesis: str
    status: TestStatus
    created_at: float
    activated_at: Optional[float] = None
    concluded_at: Optional[float] = None
    verdict: Optional[str] = None
    cost_usd: float = 0.0
    max_duration_hours: float = 48.0
    max_cost_usd: float = 2.0

    def to_dict(self) -> Dict:
        """Serialize to a JSON-safe dict."""
        return {
            "id": self.id,
            "param": self.param,
            "variant_a": self.variant_a,
            "variant_b": self.variant_b,
            "hypothesis": self.hypothesis,
            "status": self.status.value,
            "created_at": self.created_at,
            "activated_at": self.activated_at,
            "concluded_at": self.concluded_at,
            "verdict": self.verdict,
            "cost_usd": self.cost_usd,
            "max_duration_hours": self.max_duration_hours,
            "max_cost_usd": self.max_cost_usd,
        }

    @classmethod
    def from_dict(cls, d: Dict) -> AutonomousTest:
        """Deserialize from a dict."""
        return cls(
            id=d["id"],
            param=d["param"],
            variant_a=d["variant_a"],
            variant_b=d["variant_b"],
            hypothesis=d["hypothesis"],
            status=TestStatus(d["status"]),
            created_at=d["created_at"],
            activated_at=d.get("activated_at"),
            concluded_at=d.get("concluded_at"),
            verdict=d.get("verdict"),
            cost_usd=d.get("cost_usd", 0.0),
            max_duration_hours=d.get("max_duration_hours", 48.0),
            max_cost_usd=d.get("max_cost_usd", 2.0),
        )


# ── Forbidden Parameters ─────────────────────────────────────────────────

FORBIDDEN_PARAMS: List[str] = [
    "safety_gate",
    "corrigibility",
    "evidence_retention",
    "cost_limit",
    "rate_limit",
]

# Substrings that make any param forbidden.
_FORBIDDEN_SUBSTRINGS: List[str] = ["security", "auth"]


def _is_param_forbidden(param: str) -> bool:
    """Check if a parameter is forbidden from A/B testing.

    A param is forbidden if it matches an explicit entry in FORBIDDEN_PARAMS
    or contains any of the _FORBIDDEN_SUBSTRINGS (case-insensitive).
    """
    lower = param.lower()
    if param in FORBIDDEN_PARAMS:
        return True
    for substr in _FORBIDDEN_SUBSTRINGS:
        if substr in lower:
            return True
    return False


# ── A/B Test Engine ──────────────────────────────────────────────────────


class ABTestEngine:
    """Manages the full lifecycle of autonomous A/B experiments.

    Safety invariants:
    - Forbidden params are rejected at proposal time.
    - Tests must pass through GRACE_PERIOD before activation.
    - Cost and duration limits are enforced via check_safety().
    - Tests exceeding limits are auto-reverted.
    """

    # State key prefix for test storage.
    _KEY_PREFIX = "ab_test:"
    # State key for the index of all test IDs.
    _INDEX_KEY = "ab_test:_index"

    def __init__(
        self,
        evidence: EvidenceStore,
        state: StateBackend,
        config: Config,
    ) -> None:
        self._evidence = evidence
        self._state = state
        self._config = config

    # ── Core Lifecycle ────────────────────────────────────────────────

    def propose(
        self,
        param: str,
        variant_a: str,
        variant_b: str,
        hypothesis: str,
    ) -> AutonomousTest:
        """Create a new A/B test proposal.

        Raises ValueError if the param is forbidden.
        """
        if _is_param_forbidden(param):
            raise ValueError(
                f"Parameter {param!r} is forbidden from A/B testing"
            )

        test = AutonomousTest(
            id=str(uuid.uuid4()),
            param=param,
            variant_a=variant_a,
            variant_b=variant_b,
            hypothesis=hypothesis,
            status=TestStatus.PROPOSED,
            created_at=time.time(),
            max_cost_usd=self._config.budgets.autonomous_ab_usd,
        )
        self._save_test(test)
        self._index_add(test.id)
        return test

    def start_grace_period(
        self, test_id: str, duration_minutes: int = 30
    ) -> AutonomousTest:
        """Move a test into GRACE_PERIOD, allowing human veto before activation.

        The duration_minutes is informational -- actual enforcement is the
        caller's responsibility (e.g., a scheduler).
        """
        test = self._require_test(test_id)
        test.status = TestStatus.GRACE_PERIOD
        self._save_test(test)
        return test

    def veto(self, test_id: str, reason: str) -> AutonomousTest:
        """Veto a test. Records the reason as the verdict."""
        test = self._require_test(test_id)
        test.status = TestStatus.VETOED
        test.verdict = f"VETOED: {reason}"
        test.concluded_at = time.time()
        self._save_test(test)
        return test

    def activate(self, test_id: str) -> AutonomousTest:
        """Move a test from GRACE_PERIOD to ACTIVE.

        Raises ValueError if the test is not in GRACE_PERIOD.
        """
        test = self._require_test(test_id)
        if test.status != TestStatus.GRACE_PERIOD:
            raise ValueError(
                f"Test must be in grace_period to activate, "
                f"currently {test.status.value}"
            )
        test.status = TestStatus.ACTIVE
        test.activated_at = time.time()
        self._save_test(test)
        return test

    def measure(
        self, test_id: str, metric_a: float, metric_b: float
    ) -> Dict:
        """Record a measurement pair for an active test.

        Returns a comparison dict with metric_a, metric_b, and delta.
        Raises ValueError if the test is not in an active/monitoring state.
        """
        test = self._require_test(test_id)
        if test.status not in (TestStatus.ACTIVE, TestStatus.MONITORING):
            raise ValueError(
                f"Test must be active to measure, currently {test.status.value}"
            )
        delta = metric_b - metric_a
        return {
            "test_id": test.id,
            "metric_a": metric_a,
            "metric_b": metric_b,
            "delta": delta,
            "variant_b_better": delta > 0,
        }

    def conclude(self, test_id: str, verdict: str) -> AutonomousTest:
        """Conclude a test and record the result in the evidence store."""
        test = self._require_test(test_id)
        test.status = TestStatus.CONCLUDED
        test.verdict = verdict
        test.concluded_at = time.time()
        self._save_test(test)

        # Record in evidence store for future reference.
        self._evidence.record_ab_result(
            experiment_id=test.id,
            param=test.param,
            variant_a=test.variant_a,
            variant_b=test.variant_b,
            verdict=verdict,
        )
        # Track cost if any was accumulated.
        if test.cost_usd > 0:
            self._evidence.track_cost(
                surgeon="ab_test",
                cost_usd=test.cost_usd,
                operation=f"ab_test:{test.param}",
            )
        return test

    # ── Queries ───────────────────────────────────────────────────────

    def get_test(self, test_id: str) -> Optional[AutonomousTest]:
        """Retrieve a test by ID. Returns None if not found."""
        raw = self._state.get(self._key(test_id))
        if raw is None:
            return None
        return AutonomousTest.from_dict(json.loads(raw))

    def get_active_tests(self) -> List[AutonomousTest]:
        """Return all non-terminal tests (not concluded, vetoed, or reverted)."""
        ids = self._index_list()
        results: List[AutonomousTest] = []
        for tid in ids:
            test = self.get_test(tid)
            if test is not None and test.status not in _TERMINAL_STATUSES:
                results.append(test)
        return results

    # ── Safety ────────────────────────────────────────────────────────

    def check_safety(self, test_id: str) -> Dict:
        """Check if a test exceeds its duration or cost limits.

        Returns {safe: bool, reason: str}.
        If unsafe, the test is automatically moved to REVERTED status.
        """
        test = self._require_test(test_id)

        # Cost check.
        if test.cost_usd > test.max_cost_usd:
            test.status = TestStatus.REVERTED
            test.concluded_at = time.time()
            test.verdict = f"AUTO-REVERTED: cost ${test.cost_usd:.2f} exceeded limit ${test.max_cost_usd:.2f}"
            self._save_test(test)
            return {
                "safe": False,
                "reason": f"cost exceeded: ${test.cost_usd:.2f} > ${test.max_cost_usd:.2f}",
            }

        # Duration check (only meaningful if test has been activated).
        if test.activated_at is not None:
            elapsed_hours = (time.time() - test.activated_at) / 3600.0
            if elapsed_hours > test.max_duration_hours:
                test.status = TestStatus.REVERTED
                test.concluded_at = time.time()
                test.verdict = (
                    f"AUTO-REVERTED: duration {elapsed_hours:.1f}h "
                    f"exceeded limit {test.max_duration_hours:.0f}h"
                )
                self._save_test(test)
                return {
                    "safe": False,
                    "reason": (
                        f"duration exceeded: {elapsed_hours:.1f}h > "
                        f"{test.max_duration_hours:.0f}h"
                    ),
                }

        return {"safe": True, "reason": "within limits"}

    # ── Internal Persistence ──────────────────────────────────────────

    def _save_test(self, test: AutonomousTest) -> None:
        """Persist a test to the state backend."""
        self._state.set(self._key(test.id), json.dumps(test.to_dict()))

    def _require_test(self, test_id: str) -> AutonomousTest:
        """Load a test or raise KeyError if missing."""
        test = self.get_test(test_id)
        if test is None:
            raise KeyError(f"Test {test_id!r} not found")
        return test

    def _index_add(self, test_id: str) -> None:
        """Add a test ID to the index list."""
        self._state.list_push(self._INDEX_KEY, test_id)

    def _index_list(self) -> List[str]:
        """Return all indexed test IDs."""
        return self._state.list_range(self._INDEX_KEY, 0, -1)

    @staticmethod
    def _key(test_id: str) -> str:
        """State backend key for a test."""
        return f"ab_test:{test_id}"
