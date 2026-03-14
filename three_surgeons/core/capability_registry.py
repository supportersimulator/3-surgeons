"""Capability Registry — per-capability level tracking with Posture state machine.

Tracks 8 capabilities at L1/L2/L3 independently. Emits CapabilityChange
events on transitions. Implements Phase 9 C6 Posture state machine.

Hardening (V17-V22): threading locks, event batching, declarative probes,
Redis persistence, probe-after-transition, adapter protocol.

Design: docs/plans/2026-03-13-capability-registry-design.md
"""
from __future__ import annotations

import enum
import json
import logging
import threading
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Callable, Dict, List, Optional


class Capability(enum.Enum):
    """The 8 independently-tracked capabilities."""

    EVIDENCE_STORE = "evidence_store"
    CROSS_EXAM = "cross_exam"
    STATE_BACKEND = "state_backend"
    SKILL_SUGGESTIONS = "skill_suggestions"
    PROJECT_MEMORY = "project_memory"
    HEALTH_MONITORING = "health_monitoring"
    LLM_BACKEND = "llm_backend"
    EVENT_BUS = "event_bus"


class Posture(enum.Enum):
    """Overall system health posture (Phase 9 C6).

    State machine:
        NOMINAL → DEGRADED (any capability drops below baseline)
        DEGRADED → RECOVERING (all capabilities restored to baseline)
        RECOVERING → NOMINAL (3 consecutive healthy probes)
        RECOVERING → DEGRADED (capability drops again during recovery)
        * → SAFE_MODE (explicit enter_safe_mode() — forces all caps to L1)
        SAFE_MODE → RECOVERING (explicit exit_safe_mode() — restores pre-safe levels)
    """

    NOMINAL = "nominal"
    DEGRADED = "degraded"
    RECOVERING = "recovering"
    SAFE_MODE = "safe_mode"


@dataclass
class CapabilityChange:
    """Record of a single capability level change."""

    capability: str
    old_level: int
    new_level: int
    reason: str
    user_summary: str
    recovery_hint: str

    @property
    def is_upgrade(self) -> bool:
        return self.new_level > self.old_level


logger = logging.getLogger(__name__)


# --- Declarative Probe Mapping (Task 3) ---
# Lazy-loaded to avoid circular imports with upgrade.py.
# Each rule: capability, requires (set of InfraCapability), level, reason, user_summary, recovery_hint.
# Last matching rule per capability wins (most specific rules go last).

_PROBE_RULES_CACHE: Optional[list] = None
_L1_DEFAULTS_CACHE: Optional[dict] = None


def _get_probe_rules() -> list:
    """Return probe rules, importing InfraCapability lazily."""
    global _PROBE_RULES_CACHE
    if _PROBE_RULES_CACHE is not None:
        return _PROBE_RULES_CACHE

    from three_surgeons.core.upgrade import InfraCapability

    _PROBE_RULES_CACHE = [
        # --- Evidence Store ---
        {"capability": Capability.EVIDENCE_STORE, "requires": {InfraCapability.REDIS},
         "level": 2, "reason": "Redis-backed persistence",
         "user_summary": "Evidence persists across sessions via Redis", "recovery_hint": ""},
        {"capability": Capability.EVIDENCE_STORE, "requires": {InfraCapability.CONTEXTDNA},
         "level": 2, "reason": "Redis-backed persistence",
         "user_summary": "Evidence persists across sessions via Redis", "recovery_hint": ""},
        {"capability": Capability.EVIDENCE_STORE,
         "requires": {InfraCapability.LOCAL_LLM, InfraCapability.REDIS, InfraCapability.CONTEXTDNA, InfraCapability.IDE_EVENT_BUS},
         "level": 3, "reason": "PostgreSQL + bidirectional sync",
         "user_summary": "Evidence stored in PostgreSQL with bidirectional sync to SQLite", "recovery_hint": ""},

        # --- Cross-Exam ---
        {"capability": Capability.CROSS_EXAM, "requires": {InfraCapability.LOCAL_LLM},
         "level": 2, "reason": "Local LLM available",
         "user_summary": "2-surgeon cross-examination: Atlas + Neurologist", "recovery_hint": ""},
        {"capability": Capability.CROSS_EXAM,
         "requires": {InfraCapability.LOCAL_LLM, InfraCapability.REDIS, InfraCapability.CONTEXTDNA, InfraCapability.IDE_EVENT_BUS},
         "level": 3, "reason": "3-surgeon team available",
         "user_summary": "Full 3-surgeon cross-examination: Atlas + Neurologist + Cardiologist", "recovery_hint": ""},

        # --- State Backend ---
        {"capability": Capability.STATE_BACKEND, "requires": {InfraCapability.REDIS},
         "level": 2, "reason": "Redis shared state",
         "user_summary": "Shared state via Redis — cross-process coordination enabled", "recovery_hint": ""},
        {"capability": Capability.STATE_BACKEND,
         "requires": {InfraCapability.LOCAL_LLM, InfraCapability.REDIS, InfraCapability.CONTEXTDNA, InfraCapability.IDE_EVENT_BUS},
         "level": 3, "reason": "Redis + PostgreSQL with Celery",
         "user_summary": "Full shared state: Redis coordination + PostgreSQL warehouse", "recovery_hint": ""},

        # --- Skill Suggestions ---
        {"capability": Capability.SKILL_SUGGESTIONS, "requires": {InfraCapability.LOCAL_LLM},
         "level": 2, "reason": "Local LLM classification",
         "user_summary": "Context-weighted skill suggestions via local LLM", "recovery_hint": ""},
        {"capability": Capability.SKILL_SUGGESTIONS, "requires": {InfraCapability.IDE_EVENT_BUS},
         "level": 3, "reason": "IDE event bus + project memory",
         "user_summary": "Real-time skill suggestions via IDE event bus and project memory", "recovery_hint": ""},

        # --- Project Memory ---
        {"capability": Capability.PROJECT_MEMORY, "requires": {InfraCapability.REDIS},
         "level": 2, "reason": "File-persisted across sessions",
         "user_summary": "Project memory persists across sessions", "recovery_hint": ""},
        {"capability": Capability.PROJECT_MEMORY, "requires": {InfraCapability.CONTEXTDNA},
         "level": 2, "reason": "File-persisted across sessions",
         "user_summary": "Project memory persists across sessions", "recovery_hint": ""},
        {"capability": Capability.PROJECT_MEMORY,
         "requires": {InfraCapability.LOCAL_LLM, InfraCapability.REDIS, InfraCapability.CONTEXTDNA, InfraCapability.IDE_EVENT_BUS},
         "level": 3, "reason": "Full ContextDNA heavy mode",
         "user_summary": "Full project memory: PostgreSQL warehouse, bidirectional sync, conflict resolution", "recovery_hint": ""},

        # --- Health Monitoring ---
        {"capability": Capability.HEALTH_MONITORING, "requires": {InfraCapability.REDIS},
         "level": 2, "reason": "Automated sentinel probes",
         "user_summary": "Automated health monitoring with sentinel and scheduled probes", "recovery_hint": ""},
        {"capability": Capability.HEALTH_MONITORING, "requires": {InfraCapability.IDE_EVENT_BUS},
         "level": 3, "reason": "Live WebSocket health stream",
         "user_summary": "Live health monitoring via WebSocket with Cardiologist EKG", "recovery_hint": ""},

        # --- LLM Backend ---
        {"capability": Capability.LLM_BACKEND, "requires": {InfraCapability.LOCAL_LLM},
         "level": 2, "reason": "Local LLM with API fallback",
         "user_summary": "Local LLM handles classification/extraction, API fallback available", "recovery_hint": ""},
        {"capability": Capability.LLM_BACKEND,
         "requires": {InfraCapability.LOCAL_LLM, InfraCapability.REDIS, InfraCapability.CONTEXTDNA, InfraCapability.IDE_EVENT_BUS},
         "level": 3, "reason": "Hybrid routing with priority queue",
         "user_summary": "Hybrid LLM routing: local + external with priority queue and GPU lock", "recovery_hint": ""},

        # --- Event Bus ---
        {"capability": Capability.EVENT_BUS, "requires": {InfraCapability.IDE_EVENT_BUS},
         "level": 3, "reason": "WebSocket bidirectional",
         "user_summary": "Real-time bidirectional events via WebSocket — IDE file/selection events", "recovery_hint": ""},
    ]
    return _PROBE_RULES_CACHE


def _get_l1_defaults() -> dict:
    """Return L1 default metadata per capability."""
    global _L1_DEFAULTS_CACHE
    if _L1_DEFAULTS_CACHE is not None:
        return _L1_DEFAULTS_CACHE

    _L1_DEFAULTS_CACHE = {
        Capability.EVIDENCE_STORE: {"reason": "SQLite local store", "user_summary": "Evidence stored locally in SQLite", "recovery_hint": "Start Redis: docker compose up -d redis"},
        Capability.CROSS_EXAM: {"reason": "Atlas only", "user_summary": "Single-surgeon analysis (Atlas)", "recovery_hint": "Install local LLM for 2-surgeon cross-exam"},
        Capability.STATE_BACKEND: {"reason": "In-memory with SQLite fallback", "user_summary": "Local state only — no cross-process sharing", "recovery_hint": "Start Redis: docker compose up -d redis"},
        Capability.SKILL_SUGGESTIONS: {"reason": "Static matching", "user_summary": "Skill suggestions based on static manifest matching", "recovery_hint": "Install local LLM for smarter suggestions"},
        Capability.PROJECT_MEMORY: {"reason": "Session-scoped", "user_summary": "Project memory is session-scoped — lost on restart", "recovery_hint": "Enable ContextDNA for persistent project memory"},
        Capability.HEALTH_MONITORING: {"reason": "CLI gains-gate only", "user_summary": "Manual health checks via gains-gate CLI", "recovery_hint": "Start Redis for automated monitoring"},
        Capability.LLM_BACKEND: {"reason": "External API only", "user_summary": "LLM via external API (your configured provider)", "recovery_hint": "Install local LLM (MLX/Ollama/LM Studio) for faster local processing"},
        Capability.EVENT_BUS: {"reason": "No event bus", "user_summary": "No real-time events — poll-based updates only", "recovery_hint": "Start event bus: 3s serve --event-bus"},
    }
    return _L1_DEFAULTS_CACHE


# Public alias for test access
def get_probe_rules() -> list:
    """Public accessor for PROBE_RULES (test-friendly)."""
    return _get_probe_rules()


PROBE_RULES = property(lambda self: _get_probe_rules())  # type: ignore[assignment]


class CapabilityRegistry:
    """Per-capability level tracking with diff detection.

    Each of 8 capabilities is tracked at L1 (standalone), L2 (enhanced),
    or L3 (full suite). Changes are captured as CapabilityChange events
    and cleared on read (diff-then-clear pattern).

    Hardening features:
    - Thread-safe via per-registry lock (Task 1)
    - Event batching via batch_events() context manager (Task 2)
    - Declarative probe mapping via PROBE_RULES (Task 3)
    - Redis persistence via persist_to_redis/rehydrate_from_redis (Task 4)
    - Probe-after-transition callback (Task 5)
    - Adapter protocol via register_probe/run_probes (Task 6)
    """

    RECOVERY_PROBES_REQUIRED = 3

    def __init__(
        self,
        event_log: Optional["UpgradeEventLog"] = None,
        event_bus: Optional["EventBus"] = None,
        recheck_fn: Optional[Callable[[str], None]] = None,
    ) -> None:
        self._state: Dict[Capability, int] = {cap: 1 for cap in Capability}
        self._previous: Dict[Capability, int] = {cap: 1 for cap in Capability}
        self._pending_changes: List[CapabilityChange] = []
        self._posture = Posture.NOMINAL
        self._consecutive_healthy = 0
        self._event_log = event_log
        self._event_bus = event_bus
        self._batch_posture = False
        self._lock = threading.Lock()
        self._batching_events = False
        self._recheck_fn = recheck_fn
        self._custom_probes: list = []

    @property
    def posture(self) -> Posture:
        return self._posture

    def get_level(self, capability: Capability) -> int:
        return self._state[capability]

    def set_level(
        self,
        capability: Capability,
        level: int,
        reason: str,
        user_summary: str = "",
        recovery_hint: str = "",
    ) -> None:
        with self._lock:
            self._set_level_locked(capability, level, reason, user_summary, recovery_hint)

    def _set_level_locked(
        self,
        capability: Capability,
        level: int,
        reason: str,
        user_summary: str = "",
        recovery_hint: str = "",
    ) -> None:
        """Internal set_level — caller MUST hold self._lock."""
        level = max(1, min(3, level))
        old = self._state[capability]
        if old == level:
            return
        self._state[capability] = level
        self._pending_changes.append(
            CapabilityChange(
                capability=capability.value,
                old_level=old,
                new_level=level,
                reason=reason,
                user_summary=user_summary,
                recovery_hint=recovery_hint,
            )
        )
        if self._event_log:
            event = "capability_upgrade" if level > old else "capability_downgrade"
            self._event_log.record(
                event,
                from_phase=old,
                to_phase=level,
                details=f"{capability.value}: {reason}",
            )
        if not self._batch_posture:
            self._update_posture()
        logger.info(
            "Capability %s: L%d → L%d (%s)", capability.value, old, level, reason
        )
        if self._event_bus and not self._batching_events:
            self._event_bus.emit(
                "capability.changed",
                {
                    "capability": capability.value,
                    "old_level": old,
                    "new_level": level,
                    "reason": reason,
                    "user_summary": user_summary,
                    "recovery_hint": recovery_hint,
                },
                source="capability_registry",
            )
        # Probe-after-transition: schedule recheck on downgrade
        if level < old and self._recheck_fn and not self._batch_posture:
            try:
                self._recheck_fn(capability.value)
            except Exception as exc:
                logger.warning("Recheck callback failed for %s: %s", capability.value, exc)

    def diff(self) -> List[CapabilityChange]:
        with self._lock:
            changes = list(self._pending_changes)
            self._pending_changes.clear()
            return changes

    def snapshot(self) -> dict:
        with self._lock:
            caps = {}
            changes = {c.capability: c for c in self._pending_changes}
            for cap in Capability:
                entry: dict = {"level": self._state[cap], "changed": cap.value in changes}
                if cap.value in changes:
                    c = changes[cap.value]
                    entry["change"] = {
                        "from": c.old_level,
                        "to": c.new_level,
                        "summary": c.user_summary,
                        "recovery": c.recovery_hint,
                    }
                caps[cap.value] = entry
            return {
                "capabilities": caps,
                "posture": self._posture.value,
            }

    def accept_current_as_baseline(self) -> None:
        """Snapshot current state as the baseline for degradation detection."""
        with self._lock:
            self._previous = dict(self._state)

    def mark_healthy_probe(self) -> None:
        """Record a probe where no degradation was found.
        After RECOVERY_PROBES_REQUIRED consecutive healthy probes while
        RECOVERING, transitions to NOMINAL.
        """
        with self._lock:
            if self._posture == Posture.RECOVERING:
                self._consecutive_healthy += 1
                if self._consecutive_healthy >= self.RECOVERY_PROBES_REQUIRED:
                    self._posture = Posture.NOMINAL
                    self._consecutive_healthy = 0
                    logger.info("Posture: RECOVERING → NOMINAL after %d healthy probes",
                                self.RECOVERY_PROBES_REQUIRED)

    def enter_safe_mode(self, reason: str = "manual safe mode") -> None:
        """Force all capabilities to L1 (emergency brake).

        Saves current levels so exit_safe_mode() can restore them.
        Transitions posture to SAFE_MODE regardless of current state.
        """
        with self._lock:
            self._safe_mode_saved = dict(self._state)
            self._batch_posture = True
            for cap in Capability:
                self._set_level_locked(cap, 1, reason=reason,
                               user_summary="Safe mode — all capabilities reduced to L1",
                               recovery_hint="Exit safe mode to restore previous levels")
            self._batch_posture = False
            old_posture = self._posture
            self._posture = Posture.SAFE_MODE
            self._consecutive_healthy = 0
            logger.warning("Posture: %s → SAFE_MODE (%s)", old_posture.value, reason)
            if self._event_bus:
                self._event_bus.emit(
                    "posture.changed",
                    {"posture": "safe_mode", "previous": old_posture.value,
                     "reason": reason},
                    source="capability_registry",
                )

    def exit_safe_mode(self, reason: str = "safe mode cleared") -> None:
        """Restore capabilities saved before safe mode.

        Transitions posture to RECOVERING (requires healthy probes to reach NOMINAL).
        """
        with self._lock:
            if self._posture != Posture.SAFE_MODE:
                logger.warning("exit_safe_mode called but posture is %s", self._posture.value)
                return
            saved = getattr(self, "_safe_mode_saved", None)
            if saved:
                self._batch_posture = True
                for cap in Capability:
                    self._set_level_locked(cap, saved[cap], reason=reason)
                self._batch_posture = False
            old_posture = self._posture
            self._posture = Posture.RECOVERING
            self._consecutive_healthy = 0
            logger.info("Posture: SAFE_MODE → RECOVERING (%s)", reason)
            if self._event_bus:
                self._event_bus.emit(
                    "posture.changed",
                    {"posture": "recovering", "previous": old_posture.value,
                     "reason": reason},
                    source="capability_registry",
                )

    @contextmanager
    def batch_events(self):
        """Context manager that batches capability events.

        Within this block, event_bus emissions are deferred. On exit, one net
        event per capability is emitted (only if net level changed).
        Posture is also deferred and recalculated once on exit.
        """
        with self._lock:
            snapshot_before = dict(self._state)
            self._batching_events = True
            self._batch_posture = True

        try:
            yield
        finally:
            with self._lock:
                self._batching_events = False
                self._batch_posture = False
                # Emit one net event per capability that actually changed
                if self._event_bus:
                    for cap in Capability:
                        old = snapshot_before[cap]
                        new = self._state[cap]
                        if old != new:
                            self._event_bus.emit(
                                "capability.changed",
                                {
                                    "capability": cap.value,
                                    "old_level": old,
                                    "new_level": new,
                                    "reason": "batched",
                                    "user_summary": "",
                                    "recovery_hint": "",
                                },
                                source="capability_registry",
                            )
                self._update_posture()

    def save(self, path: "Path") -> None:
        """Persist current state to JSON file."""
        from pathlib import Path as _Path

        data = {
            "capabilities": {cap.value: self._state[cap] for cap in Capability},
            "posture": self._posture.value,
        }
        p = _Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(data, indent=2))

    def load(self, path: "Path") -> None:
        """Load state from JSON file. Emits diffs for any changes from current."""
        from pathlib import Path as _Path

        p = _Path(path)
        if not p.is_file():
            return
        try:
            data = json.loads(p.read_text())
        except (json.JSONDecodeError, OSError):
            logger.warning("Failed to load capability state from %s", path)
            return
        caps = data.get("capabilities", {})
        for cap in Capability:
            level = caps.get(cap.value)
            if level is not None and isinstance(level, int):
                self.set_level(cap, level, reason="restored from saved state")
        posture_str = data.get("posture")
        if posture_str:
            try:
                self._posture = Posture(posture_str)
            except ValueError:
                pass

    # --- Redis Persistence (Task 4) ---

    def persist_to_redis(self, redis_client) -> None:
        """Persist current state to Redis for cross-restart survival."""
        try:
            redis_client.hset(
                "capability:state",
                mapping={cap.value: str(self._state[cap]) for cap in Capability},
            )
            redis_client.set("capability:posture", self._posture.value)
        except Exception as exc:
            logger.warning("Failed to persist capability state to Redis: %s", exc)

    def rehydrate_from_redis(self, redis_client) -> None:
        """Restore state from Redis. If Redis is down, start DEGRADED."""
        try:
            redis_client.ping()
        except Exception:
            logger.warning("Redis unreachable during rehydrate — starting DEGRADED")
            self._posture = Posture.DEGRADED
            return

        try:
            state = redis_client.hgetall("capability:state")
            if state:
                for cap in Capability:
                    key = cap.value
                    # Redis may return bytes keys
                    val = state.get(key) or state.get(key.encode() if isinstance(key, str) else key)
                    if val is not None:
                        if isinstance(val, bytes):
                            val = val.decode()
                        try:
                            self._state[cap] = max(1, min(3, int(val)))
                        except (ValueError, TypeError):
                            pass

            posture_str = redis_client.get("capability:posture")
            if posture_str:
                if isinstance(posture_str, bytes):
                    posture_str = posture_str.decode()
                try:
                    self._posture = Posture(posture_str)
                except ValueError:
                    pass
        except Exception as exc:
            logger.warning("Failed to rehydrate from Redis: %s", exc)
            self._posture = Posture.DEGRADED

    # --- Adapter Protocol (Task 6) ---

    def register_probe(self, probe) -> None:
        """Register a custom probe for run_probes()."""
        self._custom_probes.append(probe)

    def run_probes(self) -> dict:
        """Run all registered custom probes. Returns {name: passed}."""
        results: dict = {}
        for probe in self._custom_probes:
            try:
                results[probe.name()] = probe.probe()
            except Exception as exc:
                logger.warning("Probe %s failed: %s", probe.name(), exc)
                results[probe.name()] = False
        return results

    # --- Declarative Probe Application (Task 3) ---

    def apply_probe(self, probe_result: "ProbeResult") -> List[CapabilityChange]:
        """Map EcosystemProbe results to per-capability levels via PROBE_RULES.

        Declarative rules replace the original hardcoded conditionals.
        Last matching rule per capability wins (most specific rules last).
        """
        caps = set(probe_result.capabilities)
        rules = _get_probe_rules()
        defaults = _get_l1_defaults()

        with self._lock:
            self._batch_posture = True

            # Evaluate rules: last matching rule per capability wins
            best: Dict[Capability, dict] = {}
            for rule in rules:
                if rule["requires"].issubset(caps):
                    cap = rule["capability"]
                    if cap not in best or rule["level"] >= best[cap]["level"]:
                        best[cap] = rule

            # Apply best match or L1 default for each capability
            for cap in Capability:
                if cap in best:
                    r = best[cap]
                    self._set_level_locked(cap, r["level"], reason=r["reason"],
                                           user_summary=r["user_summary"],
                                           recovery_hint=r["recovery_hint"])
                else:
                    d = defaults[cap]
                    self._set_level_locked(cap, 1, reason=d["reason"],
                                           user_summary=d["user_summary"],
                                           recovery_hint=d["recovery_hint"])

            self._batch_posture = False
            self._update_posture()

        return self.diff()

    def _update_posture(self) -> None:
        """Recalculate posture after a level change."""
        if self._posture == Posture.SAFE_MODE:
            return  # Safe mode exits only via explicit exit_safe_mode()
        old_posture = self._posture
        any_below_baseline = any(
            self._state[c] < self._previous.get(c, 1) for c in Capability
        )
        if any_below_baseline:
            self._posture = Posture.DEGRADED
            self._consecutive_healthy = 0
        elif self._posture == Posture.DEGRADED:
            # Was degraded, no longer below baseline → recovering
            self._posture = Posture.RECOVERING
            self._consecutive_healthy = 0
        if self._posture != old_posture and self._event_bus:
            self._event_bus.emit(
                "posture.changed",
                {"posture": self._posture.value, "previous": old_posture.value},
                source="capability_registry",
            )
