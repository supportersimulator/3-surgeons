"""Quality gates for system health verification.

Three gate types extracted from gains-gate.sh, cardio-gate.sh, and
corrigibility-gate.sh -- Python rewrite with configurable checks.

- GainsGate: verifies infrastructure health (state, evidence, endpoints)
- CardioGate: chains rate-limit check + gains gate + optional cross-exam
- CorrigibilityGate: checks proposed actions against safety invariants
"""
from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional

from three_surgeons.core.config import Config
from three_surgeons.core.evidence import EvidenceStore
from three_surgeons.core.state import StateBackend


# ── Result Dataclasses ────────────────────────────────────────────────


@dataclass
class CheckResult:
    """Outcome of a single health check within a gate."""

    name: str
    passed: bool
    message: str
    critical: bool = False


@dataclass
class GateResult:
    """Aggregate outcome of running a gate (collection of checks)."""

    passed: bool
    checks: List[CheckResult]
    summary: str
    duration_ms: float


# ── GainsGate ─────────────────────────────────────────────────────────


class GainsGate:
    """Verifies infrastructure health before proceeding.

    Runs configurable checks against state backend, evidence store,
    and LLM endpoints. Gate passes only if all critical checks pass.

    Default checks (from gains-gate.sh):
    - neurologist_health: pings neurologist endpoint (non-critical)
    - cardiologist_health: pings cardiologist endpoint (non-critical)
    - evidence_store: verifies evidence DB accessible (critical)
    - state_backend: verifies state backend accessible (critical)
    """

    def __init__(
        self,
        state: StateBackend,
        evidence: EvidenceStore,
        config: Config,
    ) -> None:
        self._state = state
        self._evidence = evidence
        self._config = config

        # Registry of available check functions
        self._check_registry: Dict[str, Callable[[], CheckResult]] = {
            "neurologist_health": self._check_neurologist_health,
            "cardiologist_health": self._check_cardiologist_health,
            "evidence_store": self._check_evidence_store,
            "state_backend": self._check_state_backend,
        }

    def run(self) -> GateResult:
        """Run all configured health checks. Returns aggregate GateResult.

        Gate passes only if all critical checks pass. Non-critical failures
        are recorded but do not fail the gate.
        """
        t0 = time.monotonic()
        checks: List[CheckResult] = []

        for check_name in self._config.gates.gains_gate_checks:
            check_fn = self._check_registry.get(check_name)
            if check_fn is not None:
                checks.append(check_fn())
            else:
                checks.append(
                    CheckResult(
                        name=check_name,
                        passed=False,
                        message=f"Unknown check: {check_name}",
                        critical=False,
                    )
                )

        # Always include state_backend and evidence_store if not already present
        check_names = {c.name for c in checks}
        if "state_backend" not in check_names:
            checks.append(self._check_state_backend())
        if "evidence_store" not in check_names:
            checks.append(self._check_evidence_store())

        duration_ms = (time.monotonic() - t0) * 1000

        # Gate fails if any critical check fails
        critical_failures = [c for c in checks if c.critical and not c.passed]
        passed = len(critical_failures) == 0

        # Build summary
        total = len(checks)
        passed_count = sum(1 for c in checks if c.passed)
        failed_names = [c.name for c in checks if not c.passed]
        if passed:
            summary = f"PASS: {passed_count}/{total} checks passed"
            if failed_names:
                summary += f" (non-critical failures: {', '.join(failed_names)})"
        else:
            summary = f"FAIL: {', '.join(c.name for c in critical_failures)} critical checks failed"

        return GateResult(
            passed=passed,
            checks=checks,
            summary=summary,
            duration_ms=duration_ms,
        )

    def _check_neurologist_health(self) -> CheckResult:
        """Ping neurologist endpoint. Non-critical -- local model may be offline."""
        try:
            from three_surgeons.core.models import LLMProvider

            provider = LLMProvider(self._config.neurologist)
            resp = provider.ping(timeout_s=3.0)
            if resp.ok:
                return CheckResult(
                    name="neurologist_health",
                    passed=True,
                    message=f"Neurologist operational ({resp.latency_ms}ms)",
                    critical=False,
                )
            return CheckResult(
                name="neurologist_health",
                passed=False,
                message=f"Neurologist unhealthy: {resp.content[:100]}",
                critical=False,
            )
        except Exception as exc:
            return CheckResult(
                name="neurologist_health",
                passed=False,
                message=f"Neurologist unreachable: {exc}",
                critical=False,
            )

    def _check_cardiologist_health(self) -> CheckResult:
        """Ping cardiologist endpoint. Non-critical -- API may be unavailable."""
        try:
            from three_surgeons.core.models import LLMProvider

            provider = LLMProvider(self._config.cardiologist)
            resp = provider.ping(timeout_s=3.0)
            if resp.ok:
                return CheckResult(
                    name="cardiologist_health",
                    passed=True,
                    message=f"Cardiologist operational ({resp.latency_ms}ms)",
                    critical=False,
                )
            return CheckResult(
                name="cardiologist_health",
                passed=False,
                message=f"Cardiologist unhealthy: {resp.content[:100]}",
                critical=False,
            )
        except Exception as exc:
            return CheckResult(
                name="cardiologist_health",
                passed=False,
                message=f"Cardiologist unreachable: {exc}",
                critical=False,
            )

    def _check_evidence_store(self) -> CheckResult:
        """Verify evidence DB is accessible. Critical -- needed for operation."""
        try:
            stats = self._evidence.get_stats()
            return CheckResult(
                name="evidence_store",
                passed=True,
                message=f"Evidence store accessible ({stats['total']} learnings)",
                critical=True,
            )
        except Exception as exc:
            return CheckResult(
                name="evidence_store",
                passed=False,
                message=f"Evidence store inaccessible: {exc}",
                critical=True,
            )

    def _check_state_backend(self) -> CheckResult:
        """Verify state backend is operational. Critical -- needed for operation."""
        try:
            alive = self._state.ping()
            if alive:
                return CheckResult(
                    name="state_backend",
                    passed=True,
                    message="State backend operational",
                    critical=True,
                )
            return CheckResult(
                name="state_backend",
                passed=False,
                message="State backend ping returned False",
                critical=True,
            )
        except Exception as exc:
            return CheckResult(
                name="state_backend",
                passed=False,
                message=f"State backend unreachable: {exc}",
                critical=True,
            )


# ── CardioGate ────────────────────────────────────────────────────────


class CardioGate:
    """Chains: rate limit check -> gains gate -> optional cross-exam.

    From cardio-gate.sh: Cardiologist EKG protocol. Quality degradation
    detected -> gains gate MUST pass -> optional 3-surgeon cross-exam.

    Rate limit: max 3 automated reviews per hour (tracked in state backend).
    """

    #: Maximum automated reviews per hour
    MAX_REVIEWS_PER_HOUR: int = 3

    #: State key for tracking review count
    RATE_KEY: str = "cardio_gate:reviews_this_hour"

    def __init__(
        self,
        state: StateBackend,
        evidence: EvidenceStore,
        surgery_team: object,
        config: Config,
    ) -> None:
        self._state = state
        self._evidence = evidence
        self._surgery_team = surgery_team
        self._config = config

    def run(self) -> GateResult:
        """Run cardio gate: rate limit -> gains gate -> optional cross-exam.

        Returns GateResult. If rate limit or gains gate fails, entire gate fails.
        """
        t0 = time.monotonic()
        checks: List[CheckResult] = []

        # Step 1: Rate limit check (critical)
        rate_check = self._check_rate_limit()
        checks.append(rate_check)

        # Step 2: Run gains gate checks (embedded, not nested GateResult)
        gains_gate = GainsGate(
            state=self._state,
            evidence=self._evidence,
            config=self._config,
        )
        gains_result = gains_gate.run()
        checks.extend(gains_result.checks)

        duration_ms = (time.monotonic() - t0) * 1000

        # Gate fails if any critical check fails
        critical_failures = [c for c in checks if c.critical and not c.passed]
        passed = len(critical_failures) == 0

        # Build summary
        if passed:
            total = len(checks)
            passed_count = sum(1 for c in checks if c.passed)
            summary = f"CARDIO PASS: {passed_count}/{total} checks passed"
        else:
            failed_names = [c.name for c in critical_failures]
            summary = f"CARDIO FAIL: {', '.join(failed_names)} critical checks failed"

        return GateResult(
            passed=passed,
            checks=checks,
            summary=summary,
            duration_ms=duration_ms,
        )

    def _check_rate_limit(self) -> CheckResult:
        """Check if we've exceeded the hourly review limit. Critical."""
        current = self._state.get(self.RATE_KEY)
        count = int(current) if current is not None else 0

        if count >= self.MAX_REVIEWS_PER_HOUR:
            return CheckResult(
                name="rate_limit",
                passed=False,
                message=f"Rate limited: {count}/{self.MAX_REVIEWS_PER_HOUR} reviews this hour",
                critical=True,
            )
        return CheckResult(
            name="rate_limit",
            passed=True,
            message=f"Rate OK: {count}/{self.MAX_REVIEWS_PER_HOUR} reviews this hour",
            critical=True,
        )


# ── CorrigibilityGate ─────────────────────────────────────────────────


# Default invariant patterns -- each is a (compiled regex, description) pair.
# Actions matching any pattern are flagged as unsafe.
_DEFAULT_INVARIANTS: List[tuple] = [
    (
        re.compile(
            r"\b(drop\s+(all\s+)?(database|table|collection)s?|"
            r"truncate\s+(all\s+)?table|"
            r"delete\s+(all\s+)?(production|prod)\s+data|"
            r"rm\s+-rf\s+/|"
            r"format\s+(disk|drive)|"
            r"wipe\s+(all\s+)?data|"
            r"destroy\s+(all\s+)?(database|table|data))",
            re.IGNORECASE,
        ),
        "No destructive operations without explicit approval",
    ),
    (
        re.compile(
            r"\b(bypass\s+safety|"
            r"skip\s+safety|"
            r"ignore\s+safety|"
            r"disable\s+safety|"
            r"override\s+safety|"
            r"circumvent\s+safety|"
            r"bypass\s+(constraint|check|validation|guard)|"
            r"skip\s+(constraint|check|validation|guard))",
            re.IGNORECASE,
        ),
        "No bypassing safety constraints",
    ),
    (
        re.compile(
            r"\b(modify\s+(the\s+)?gate\s+logic|"
            r"disable\s+(the\s+)?(corrigibility|gains|cardio)\s+gate|"
            r"skip\s+(the\s+)?(corrigibility|gains|cardio)\s+(gate|check)|"
            r"remove\s+(the\s+)?(corrigibility|gains|cardio)\s+gate|"
            r"bypass\s+(the\s+)?(corrigibility|gains|cardio)\s+gate)",
            re.IGNORECASE,
        ),
        "No modifying gate logic itself",
    ),
    (
        re.compile(
            r"\b(force\s+push|"
            r"--force\s+push|"
            r"push\s+--force|"
            r"git\s+push\s+-f)",
            re.IGNORECASE,
        ),
        "No force-pushing without explicit approval",
    ),
]


class CorrigibilityGate:
    """Checks proposed actions against safety invariants.

    From corrigibility-gate.sh: ensures proposed actions do not violate
    safety rules. Returns pass/fail with reasoning.

    Default invariants (configurable):
    - No destructive operations without explicit approval
    - No bypassing safety constraints
    - No modifying gate logic itself
    """

    def __init__(self, config: Config) -> None:
        self._config = config
        self._invariants = list(_DEFAULT_INVARIANTS)

    def run(self, proposed_action: str) -> GateResult:
        """Check proposed action against invariants. Returns GateResult.

        Each invariant is tested independently. Gate passes only if no
        invariants are violated.
        """
        t0 = time.monotonic()
        checks: List[CheckResult] = []

        for pattern, description in self._invariants:
            match = pattern.search(proposed_action)
            if match:
                checks.append(
                    CheckResult(
                        name="invariant_violation",
                        passed=False,
                        message=f"Blocked: {description} (matched: '{match.group()}')",
                        critical=True,
                    )
                )
            else:
                checks.append(
                    CheckResult(
                        name="invariant_check",
                        passed=True,
                        message=f"OK: {description}",
                        critical=True,
                    )
                )

        duration_ms = (time.monotonic() - t0) * 1000

        violations = [c for c in checks if not c.passed]
        passed = len(violations) == 0

        if passed:
            summary = f"CORRIGIBILITY PASS: action is safe ({len(checks)} invariants checked)"
        else:
            reasons = [c.message for c in violations]
            summary = f"CORRIGIBILITY FAIL: {'; '.join(reasons)}"

        return GateResult(
            passed=passed,
            checks=checks,
            summary=summary,
            duration_ms=duration_ms,
        )
