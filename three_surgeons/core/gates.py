"""Quality gates for system health verification.

Three gate types extracted from gains-gate.sh, cardio-gate.sh, and
corrigibility-gate.sh -- Python rewrite with configurable checks.

- GainsGate: verifies infrastructure health (state, evidence, endpoints, GPU lock, LLM, criticals)
- CardioGate: chains rate-limit check + gains gate + optional cross-exam
- CorrigibilityGate: checks proposed actions against safety invariants + structural integrity
"""
from __future__ import annotations

import os
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

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
            "gpu_lock_stale": self._check_gpu_lock_stale,
            "llm_test_query": self._check_llm_test_query,
            "critical_findings": self._check_critical_findings,
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

            neuro_cfg = self._config.neurologist
            provider = LLMProvider(neuro_cfg, fallbacks=neuro_cfg.get_fallback_configs())
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

            cardio_cfg = self._config.cardiologist
            provider = LLMProvider(cardio_cfg, fallbacks=cardio_cfg.get_fallback_configs())
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

    def _check_gpu_lock_stale(self) -> CheckResult:
        """Check if GPU lock file is stale (held by dead PID). Critical."""
        lock_path = self._config.gpu_lock_path
        if lock_path is None:
            return CheckResult(
                name="gpu_lock_stale",
                passed=True,
                message="GPU lock path not configured (skipped)",
                critical=False,
            )
        try:
            path = Path(lock_path)
            if not path.exists():
                return CheckResult(
                    name="gpu_lock_stale",
                    passed=True,
                    message="GPU lock free",
                    critical=True,
                )
            pid_str = path.read_text().strip()
            if not pid_str:
                return CheckResult(
                    name="gpu_lock_stale",
                    passed=False,
                    message="GPU lock file empty (stale)",
                    critical=True,
                )
            pid = int(pid_str)
            try:
                os.kill(pid, 0)
                return CheckResult(
                    name="gpu_lock_stale",
                    passed=True,
                    message=f"GPU lock held by PID {pid} (alive)",
                    critical=True,
                )
            except OSError:
                return CheckResult(
                    name="gpu_lock_stale",
                    passed=False,
                    message=f"GPU lock stale: PID {pid} dead",
                    critical=True,
                )
        except Exception as exc:
            return CheckResult(
                name="gpu_lock_stale",
                passed=False,
                message=f"GPU lock check error: {exc}",
                critical=True,
            )

    def _check_llm_test_query(self) -> CheckResult:
        """Send a trivial test query to the neurologist. Non-critical."""
        try:
            from three_surgeons.core.models import LLMProvider

            neuro_cfg = self._config.neurologist
            provider = LLMProvider(neuro_cfg, fallbacks=neuro_cfg.get_fallback_configs())
            resp = provider.query(
                system="Respond with OK.",
                prompt="Health check",
                max_tokens=8,
                temperature=0.0,
            )
            if resp.ok:
                return CheckResult(
                    name="llm_test_query",
                    passed=True,
                    message=f"LLM test query OK ({resp.latency_ms}ms)",
                    critical=False,
                )
            return CheckResult(
                name="llm_test_query",
                passed=False,
                message=f"LLM test query failed: {resp.content[:100]}",
                critical=False,
            )
        except Exception as exc:
            return CheckResult(
                name="llm_test_query",
                passed=False,
                message=f"LLM test query error: {exc}",
                critical=False,
            )

    def _check_critical_findings(self) -> CheckResult:
        """Check for unresolved critical findings. Critical -- must be 0."""
        try:
            count_str = self._state.get("critical_findings:count")
            count = int(count_str) if count_str is not None else 0
            if count == 0:
                return CheckResult(
                    name="critical_findings",
                    passed=True,
                    message="No unresolved critical findings",
                    critical=True,
                )
            return CheckResult(
                name="critical_findings",
                passed=False,
                message=f"{count} unresolved critical findings",
                critical=True,
            )
        except Exception as exc:
            return CheckResult(
                name="critical_findings",
                passed=True,
                message=f"Critical findings check error (defaulting pass): {exc}",
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
    """Checks proposed actions against safety invariants + structural integrity.

    From corrigibility-gate.sh: ensures proposed actions do not violate
    safety rules AND system integrity invariants hold.

    Text safety invariants (configurable):
    - No destructive operations without explicit approval
    - No bypassing safety constraints
    - No modifying gate logic itself
    - No force-pushing without explicit approval

    Structural integrity invariants (via check_integrity):
    - events_monotonic: event count never decreases
    - learnings_preserved: learning count never decreases
    - evidence_grades_preserved: evidence grades never decrease
    - service_health: key services are operational
    """

    def __init__(
        self,
        config: Config,
        state: Optional[StateBackend] = None,
        evidence: Optional[EvidenceStore] = None,
    ) -> None:
        self._config = config
        self._state = state
        self._evidence = evidence
        self._invariants = list(_DEFAULT_INVARIANTS)

    def run(self, proposed_action: str) -> GateResult:
        """Check proposed action against text safety invariants. Returns GateResult.

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

    def check_integrity(self) -> GateResult:
        """Check structural integrity invariants against state backend.

        Verifies that critical counters never decrease (events, learnings,
        evidence grades) and key services are operational.

        Returns GateResult. Gate passes only if all integrity checks pass.
        """
        t0 = time.monotonic()
        checks: List[CheckResult] = []

        if self._state is not None:
            checks.append(self._check_monotonic("events_count", "events_monotonic"))
            checks.append(self._check_monotonic("learnings_count", "learnings_preserved"))
            checks.append(self._check_monotonic("evidence_grade_sum", "evidence_grades_preserved"))
            checks.append(self._check_service_health())
        else:
            checks.append(
                CheckResult(
                    name="integrity_skipped",
                    passed=True,
                    message="No state backend -- integrity checks skipped",
                    critical=False,
                )
            )

        if self._evidence is not None:
            checks.append(self._check_evidence_operational())

        duration_ms = (time.monotonic() - t0) * 1000

        violations = [c for c in checks if c.critical and not c.passed]
        passed = len(violations) == 0

        if passed:
            summary = f"INTEGRITY PASS: {len(checks)} checks passed"
        else:
            reasons = [c.message for c in violations]
            summary = f"INTEGRITY FAIL: {'; '.join(reasons)}"

        return GateResult(
            passed=passed,
            checks=checks,
            summary=summary,
            duration_ms=duration_ms,
        )

    def _check_monotonic(self, counter_key: str, check_name: str) -> CheckResult:
        """Verify a counter in state backend never decreases."""
        try:
            current_str = self._state.get(f"integrity:{counter_key}")
            previous_str = self._state.get(f"integrity:{counter_key}:prev")

            if current_str is None:
                return CheckResult(
                    name=check_name,
                    passed=True,
                    message=f"{check_name}: no data yet (OK)",
                    critical=True,
                )

            current = int(current_str)
            if previous_str is not None:
                previous = int(previous_str)
                if current < previous:
                    return CheckResult(
                        name=check_name,
                        passed=False,
                        message=f"{check_name}: decreased from {previous} to {current}",
                        critical=True,
                    )

            return CheckResult(
                name=check_name,
                passed=True,
                message=f"{check_name}: {current} (monotonic OK)",
                critical=True,
            )
        except (TypeError, ValueError) as exc:
            return CheckResult(
                name=check_name,
                passed=True,
                message=f"{check_name}: parse error (defaulting pass): {exc}",
                critical=True,
            )

    def _check_service_health(self) -> CheckResult:
        """Verify state backend is responsive."""
        try:
            alive = self._state.ping()
            return CheckResult(
                name="service_health",
                passed=alive,
                message="State backend operational" if alive else "State backend down",
                critical=True,
            )
        except Exception as exc:
            return CheckResult(
                name="service_health",
                passed=False,
                message=f"Service health error: {exc}",
                critical=True,
            )

    def _check_evidence_operational(self) -> CheckResult:
        """Verify evidence store is accessible."""
        try:
            stats = self._evidence.get_stats()
            return CheckResult(
                name="evidence_operational",
                passed=True,
                message=f"Evidence store: {stats.get('total', 0)} items",
                critical=True,
            )
        except Exception as exc:
            return CheckResult(
                name="evidence_operational",
                passed=False,
                message=f"Evidence store error: {exc}",
                critical=True,
            )
