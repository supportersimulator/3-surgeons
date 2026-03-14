"""MCP server exposing 3-Surgeons core/ as typed tools.

Thin wrapper -- each tool delegates to the same core functions as the CLI.
Uses the FastMCP pattern from the `mcp` Python SDK when available.
Falls back to plain function definitions when the SDK is not installed,
keeping the module importable for testing and discoverability.

Run: python -m three_surgeons.mcp.server
"""
from __future__ import annotations

import logging
import os
from typing import Optional

from three_surgeons.core.ab_testing import ABTestEngine
from three_surgeons.core.cardio import ab_validate, cardio_review
from three_surgeons.core.config import Config
from three_surgeons.core.cross_exam import ReviewMode, SurgeryTeam
from three_surgeons.core.direct import ask_local, ask_remote
from three_surgeons.core.evidence import EvidenceStore
from three_surgeons.core.gates import GainsGate
from three_surgeons.core.models import LLMProvider
from three_surgeons.core.neurologist import introspect, neurologist_challenge, neurologist_pulse
from three_surgeons.core.research import research as research_fn
from three_surgeons.core.sentinel import Sentinel
from three_surgeons.core.state import MemoryBackend

logger = logging.getLogger(__name__)


def _make_neuro(config: Config) -> LLMProvider:
    """Create neurologist LLMProvider with GPU lock for local providers."""
    # ContextDNA ecosystem: use priority queue adapter (Redis GPU lock + hybrid routing)
    if os.environ.get("CONTEXTDNA_ADAPTER"):
        try:
            from context_dna.adapters import create_adapter

            adapter = create_adapter(
                priority=os.environ.get("CONTEXTDNA_LLM_PRIORITY", "ATLAS"),
                caller="3surgeons_neuro",
            )
            logger.info("Using ContextDNA priority queue adapter for neurologist")
            return LLMProvider(config.neurologist, query_adapter=adapter)
        except ImportError:
            logger.warning(
                "CONTEXTDNA_ADAPTER set but context_dna.adapters not importable; "
                "falling back"
            )

    # Standalone: file-based GPU lock for local providers
    if config.neurologist.provider in ("ollama", "mlx", "local", "vllm", "lmstudio"):
        from pathlib import Path

        from three_surgeons.core.priority_queue import make_gpu_locked_adapter

        lock_dir = Path(config.gpu_lock_path) if config.gpu_lock_path else None
        adapter = make_gpu_locked_adapter(config.neurologist, lock_dir=lock_dir)
        return LLMProvider(config.neurologist, query_adapter=adapter)
    return LLMProvider(config.neurologist)

# ── Tool registry ───────────────────────────────────────────────────────

TOOL_NAMES: list[str] = [
    "probe",
    "cross_examine",
    "consult",
    "consensus",
    "sentinel_run",
    "gains_gate",
    "ab_propose",
    "ab_start",
    "ab_measure",
    "ab_conclude",
    "neurologist_pulse_tool",
    "neurologist_challenge_tool",
    "introspect_tool",
    "ask_local_tool",
    "ask_remote_tool",
    "cardio_review_tool",
    "ab_validate_tool",
    "research_tool",
    "upgrade_probe",
    "upgrade_history",
    "capability_status",
]

# ── Dependency builders (thin, testable seams) ──────────────────────────


def _build_config() -> Config:
    """Discover and return the system Config."""
    return Config.discover()


def _build_state() -> MemoryBackend:
    """Create a fresh in-memory state backend."""
    return MemoryBackend()


def _build_evidence(config: Optional[Config] = None) -> EvidenceStore:
    """Create an evidence store from config."""
    if config is None:
        config = _build_config()
    return EvidenceStore(str(config.evidence.resolved_path))


def _build_surgery_team(
    config: Optional[Config] = None,
) -> SurgeryTeam:
    """Wire up a full SurgeryTeam from config."""
    if config is None:
        config = _build_config()
    state = _build_state()
    evidence = _build_evidence(config)
    cardio = LLMProvider(config.cardiologist)
    neuro = _make_neuro(config)
    return SurgeryTeam(
        cardiologist=cardio, neurologist=neuro, evidence=evidence, state=state
    )


def _build_ab_engine(config: Optional[Config] = None) -> ABTestEngine:
    """Wire up the A/B test engine from config."""
    if config is None:
        config = _build_config()
    state = _build_state()
    evidence = _build_evidence(config)
    return ABTestEngine(evidence=evidence, state=state, config=config)


# ── Tool implementations (pure functions, return dicts) ─────────────────


def _probe() -> dict:
    """Health check all 3 surgeons."""
    config = _build_config()
    results: dict = {}

    for name, surgeon_cfg in [
        ("cardiologist", config.cardiologist),
        ("neurologist", config.neurologist),
    ]:
        try:
            provider = LLMProvider(surgeon_cfg)
            resp = provider.ping(timeout_s=5.0)
            if resp.ok:
                results[name] = {
                    "status": "ok",
                    "latency_ms": resp.latency_ms,
                }
            else:
                results[name] = {
                    "status": "fail",
                    "error": resp.content[:200],
                }
        except Exception as exc:
            results[name] = {
                "status": "unreachable",
                "error": str(exc)[:200],
            }

    results["atlas"] = {"status": "ok", "note": "always available (this session)"}
    return results


def _cross_examine(topic: str, depth: str = "full", mode: str = "single", file_paths: Optional[list] = None) -> dict:
    """Full cross-examination protocol with iterative review support.

    Args:
        topic: The topic to cross-examine.
        depth: Depth of analysis ("full" or "quick").
        mode: Review mode — "single" (1 pass), "iterative" (up to 3), "continuous" (up to 5).
        file_paths: Optional list of file paths to include as context.
    """
    team = _build_surgery_team()
    parsed_mode = ReviewMode.from_string(mode)
    result = team.cross_examine_iterative(topic, mode=parsed_mode, depth=depth, file_paths=file_paths)
    return {
        "topic": result.topic,
        "cardiologist_report": result.cardiologist_report,
        "neurologist_report": result.neurologist_report,
        "cardiologist_exploration": result.cardiologist_exploration,
        "neurologist_exploration": result.neurologist_exploration,
        "synthesis": result.synthesis,
        "total_cost": result.total_cost,
        "total_latency_ms": result.total_latency_ms,
        "iteration_count": result.iteration_count,
        "mode_used": result.mode_used,
        "escalation_needed": result.escalation_needed,
        "unresolved_summary": result.unresolved_summary,
    }


def _consult(topic: str, file_paths: Optional[list] = None) -> dict:
    """Quick consult with both surgeons."""
    team = _build_surgery_team()
    result = team.consult(topic, file_paths=file_paths)
    return {
        "topic": result.topic,
        "cardiologist_report": result.cardiologist_report,
        "neurologist_report": result.neurologist_report,
        "total_cost": result.total_cost,
        "total_latency_ms": result.total_latency_ms,
    }


def _consensus(claim: str) -> dict:
    """Confidence-weighted consensus."""
    team = _build_surgery_team()
    result = team.consensus(claim)
    return {
        "claim": result.claim,
        "cardiologist_confidence": result.cardiologist_confidence,
        "cardiologist_assessment": result.cardiologist_assessment,
        "neurologist_confidence": result.neurologist_confidence,
        "neurologist_assessment": result.neurologist_assessment,
        "weighted_score": result.weighted_score,
        "total_cost": result.total_cost,
    }


def _sentinel_run(content: str) -> dict:
    """Run complexity vector sentinel."""
    sentinel = Sentinel()
    result = sentinel.run_cycle(content)
    return {
        "vectors_checked": result.vectors_checked,
        "vectors_triggered": result.vectors_triggered,
        "risk_level": result.risk_level,
        "overall_score": result.overall_score,
        "triggered_vectors": result.triggered_vectors,
        "recommendations": result.recommendations,
    }


def _gains_gate() -> dict:
    """Run gains gate verification."""
    config = _build_config()
    state = _build_state()
    evidence = _build_evidence(config)
    gate = GainsGate(state=state, evidence=evidence, config=config)
    result = gate.run()
    return {
        "passed": result.passed,
        "summary": result.summary,
        "duration_ms": result.duration_ms,
        "checks": [
            {
                "name": c.name,
                "passed": c.passed,
                "message": c.message,
                "critical": c.critical,
            }
            for c in result.checks
        ],
    }


def _ab_propose(
    param: str, variant_a: str, variant_b: str, hypothesis: str
) -> dict:
    """Propose an A/B test."""
    engine = _build_ab_engine()
    try:
        test = engine.propose(
            param=param,
            variant_a=variant_a,
            variant_b=variant_b,
            hypothesis=hypothesis,
        )
        return test.to_dict()
    except ValueError as exc:
        return {"error": str(exc)}


def _ab_start(test_id: str) -> dict:
    """Start grace period for A/B test."""
    engine = _build_ab_engine()
    try:
        test = engine.start_grace_period(test_id)
        return test.to_dict()
    except (KeyError, ValueError) as exc:
        return {"error": str(exc)}


def _ab_measure(test_id: str, metric_a: float, metric_b: float) -> dict:
    """Record A/B test measurement."""
    engine = _build_ab_engine()
    try:
        return engine.measure(test_id, metric_a=metric_a, metric_b=metric_b)
    except (KeyError, ValueError) as exc:
        return {"error": str(exc)}


def _ab_conclude(test_id: str, verdict: str) -> dict:
    """Conclude an A/B test."""
    engine = _build_ab_engine()
    try:
        test = engine.conclude(test_id, verdict)
        return test.to_dict()
    except (KeyError, ValueError) as exc:
        return {"error": str(exc)}


def _neurologist_pulse_impl() -> dict:
    """System health pulse check via neurologist."""
    config = _build_config()
    neuro = _make_neuro(config)
    state = _build_state()
    evidence = _build_evidence(config)
    result = neurologist_pulse(
        neuro, state_backend=state, evidence_store=evidence,
        gpu_lock_path=config.gpu_lock_path,
    )
    return {
        "healthy": result.healthy,
        "summary": result.summary,
        "checks": {
            name: {"ok": c.ok, "detail": c.detail, "latency_ms": c.latency_ms}
            for name, c in result.checks.items()
        },
    }


def _neurologist_challenge_impl(topic: str, file_paths: Optional[list] = None, rounds: int = 1) -> dict:
    """Corrigibility skeptic challenge."""
    config = _build_config()
    neuro = _make_neuro(config)
    evidence = _build_evidence(config)

    if rounds > 1:
        from three_surgeons.core.neurologist import neurologist_challenge_iterative

        result = neurologist_challenge_iterative(
            topic, neuro, evidence_store=evidence,
            file_paths=file_paths, rounds=min(rounds, 3),
        )
        return {
            "topic": result.topic,
            "challenges": [
                {"claim": c.claim, "challenge": c.challenge,
                 "severity": c.severity, "suggested_test": c.suggested_test}
                for c in result.challenges
            ],
            "iteration_count": result.iteration_count,
        }
    else:
        result = neurologist_challenge(topic, neuro, evidence_store=evidence, file_paths=file_paths)
        return {
            "topic": result.topic,
            "challenges": [
                {"claim": c.claim, "challenge": c.challenge,
                 "severity": c.severity, "suggested_test": c.suggested_test}
                for c in result.challenges
            ],
        }


def _introspect_impl() -> dict:
    """Ask each surgeon to self-report capabilities."""
    config = _build_config()
    providers = {}
    try:
        providers["cardiologist"] = LLMProvider(config.cardiologist)
    except Exception:
        pass
    try:
        providers["neurologist"] = _make_neuro(config)
    except Exception:
        pass
    results = introspect(providers)
    return {
        name: {
            "model": r.model,
            "capabilities": r.capabilities,
            "limitations": r.limitations,
            "ok": r.ok,
            "latency_ms": r.latency_ms,
        }
        for name, r in results.items()
    }


def _ask_local_impl(prompt: str) -> dict:
    """Direct query to the neurologist."""
    config = _build_config()
    neuro = _make_neuro(config)
    resp = ask_local(prompt, neuro)
    return {"ok": resp.ok, "content": resp.content}


def _ask_remote_impl(prompt: str) -> dict:
    """Direct query to the cardiologist."""
    config = _build_config()
    cardio = LLMProvider(config.cardiologist)
    resp = ask_remote(prompt, cardio)
    return {"ok": resp.ok, "content": resp.content, "cost_usd": resp.cost_usd}


def _cardio_review_impl(topic: str, git_context: Optional[str] = None, file_paths: Optional[list] = None) -> dict:
    """Cardiologist cross-examination review."""
    team = _build_surgery_team()
    evidence = _build_evidence()
    result = cardio_review(topic, team, evidence_store=evidence, git_context=git_context, file_paths=file_paths)
    return {
        "topic": result.topic,
        "cardiologist_findings": result.cardiologist_findings,
        "neurologist_blind_spots": result.neurologist_blind_spots,
        "synthesis": result.synthesis,
        "dissent": result.dissent,
        "recommendations": result.recommendations,
    }


def _ab_validate_impl(description: str) -> dict:
    """Quick 3-surgeon fix validation."""
    team = _build_surgery_team()
    result = ab_validate(description, team)
    return {
        "verdict": result.verdict,
        "reasoning": result.reasoning,
        "surgeon_votes": result.surgeon_votes,
    }


def _research_impl(topic: str) -> dict:
    """Self-directed research."""
    config = _build_config()
    cardio = LLMProvider(config.cardiologist)
    result = research_fn(topic, cardio)
    return {
        "topic": result.topic,
        "findings": result.findings,
        "sources": result.sources,
        "cost_usd": result.cost_usd,
    }


def _upgrade_log_path() -> "Path":
    """Return the path to the upgrade event log."""
    from pathlib import Path

    return Path.home() / ".3surgeons" / "upgrade.log"


def _upgrade_probe_impl() -> dict:
    """Probe ecosystem and report detected phase + available infrastructure."""
    from three_surgeons.core.upgrade import EcosystemProbe

    probe = EcosystemProbe()
    result = probe.run()
    config = _build_config()
    return {
        "current_phase": config.phase,
        "detected_phase": result.detected_phase,
        "capabilities": [c.value for c in result.capabilities],
        "details": result.details,
    }


def _upgrade_history_impl() -> str:
    """Show upgrade event log."""
    import json

    from three_surgeons.core.upgrade import UpgradeEventLog

    log_path = _upgrade_log_path()
    log = UpgradeEventLog(log_path)
    entries = log.read_all()
    return json.dumps(entries, indent=2) if entries else "No upgrade history."


# ── Capability Registry ─────────────────────────────────────────────

def _capability_status(
    verbose: bool = False,
    capability: str | None = None,
) -> dict:
    """Query per-capability levels and system posture.

    Returns current level (L1/L2/L3) for each of 8 capabilities,
    any pending changes with user-facing summaries and recovery hints,
    and overall system posture (nominal/degraded/recovering/safe_mode).

    Args:
        verbose: Include probe details and recovery hints for all capabilities.
        capability: Filter to a single capability name.

    Returns:
        Dict with capabilities, posture, and any pending changes.
    """
    from pathlib import Path

    from three_surgeons.core.capability_registry import CapabilityRegistry

    reg = CapabilityRegistry()

    # Load persisted state
    state_path = Path.home() / ".3surgeons" / ".capability_state.json"
    if state_path.is_file():
        reg.load(state_path)

    # Run fresh probe and apply
    try:
        from three_surgeons.core.upgrade import EcosystemProbe

        probe = EcosystemProbe()
        probe_result = probe.run()
        reg.apply_probe(probe_result)
    except Exception as exc:
        logger.warning("Probe failed during capability_status: %s", exc)

    # Save updated state
    state_path.parent.mkdir(parents=True, exist_ok=True)
    reg.save(state_path)

    snap = reg.snapshot()

    # Filter to single capability if requested
    if capability:
        filtered = {capability: snap["capabilities"].get(capability, {"level": 1, "changed": False})}
        snap["capabilities"] = filtered

    return snap


# ── FastMCP wiring (optional -- gracefully degrades) ────────────────────

_mcp_app = None

try:
    from mcp.server.fastmcp import FastMCP

    _mcp_app = FastMCP("3-surgeons")

    @_mcp_app.tool()
    def probe() -> dict:
        """Health check all 3 surgeons."""
        return _probe()

    @_mcp_app.tool()
    def cross_examine(topic: str, depth: str = "full", mode: str = "single", file_paths: list | None = None) -> dict:
        """Full cross-examination protocol with iterative review support."""
        return _cross_examine(topic, depth=depth, mode=mode, file_paths=file_paths)

    @_mcp_app.tool()
    def consult(topic: str, file_paths: list | None = None) -> dict:
        """Quick consult with both surgeons."""
        return _consult(topic, file_paths=file_paths)

    @_mcp_app.tool()
    def consensus(claim: str) -> dict:
        """Confidence-weighted consensus."""
        return _consensus(claim)

    @_mcp_app.tool()
    def sentinel_run(content: str) -> dict:
        """Run complexity vector sentinel."""
        return _sentinel_run(content)

    @_mcp_app.tool()
    def gains_gate() -> dict:
        """Run gains gate verification."""
        return _gains_gate()

    @_mcp_app.tool()
    def ab_propose(
        param: str, variant_a: str, variant_b: str, hypothesis: str
    ) -> dict:
        """Propose an A/B test."""
        return _ab_propose(
            param=param,
            variant_a=variant_a,
            variant_b=variant_b,
            hypothesis=hypothesis,
        )

    @_mcp_app.tool()
    def ab_start(test_id: str) -> dict:
        """Start grace period for A/B test."""
        return _ab_start(test_id)

    @_mcp_app.tool()
    def ab_measure(test_id: str, metric_a: float, metric_b: float) -> dict:
        """Record A/B test measurement."""
        return _ab_measure(test_id, metric_a=metric_a, metric_b=metric_b)

    @_mcp_app.tool()
    def ab_conclude(test_id: str, verdict: str) -> dict:
        """Conclude an A/B test."""
        return _ab_conclude(test_id, verdict=verdict)

    @_mcp_app.tool()
    def neurologist_pulse_tool() -> dict:
        """System health pulse check via neurologist."""
        return _neurologist_pulse_impl()

    @_mcp_app.tool()
    def neurologist_challenge_tool(topic: str, file_paths: list | None = None, rounds: int = 1) -> dict:
        """Corrigibility skeptic challenge on a topic."""
        return _neurologist_challenge_impl(topic, file_paths=file_paths, rounds=rounds)

    @_mcp_app.tool()
    def introspect_tool() -> dict:
        """Ask each surgeon to self-report capabilities."""
        return _introspect_impl()

    @_mcp_app.tool()
    def ask_local_tool(prompt: str) -> dict:
        """Direct query to the neurologist (local model)."""
        return _ask_local_impl(prompt)

    @_mcp_app.tool()
    def ask_remote_tool(prompt: str) -> dict:
        """Direct query to the cardiologist (remote model)."""
        return _ask_remote_impl(prompt)

    @_mcp_app.tool()
    def cardio_review_tool(topic: str, git_context: str = "", file_paths: list | None = None) -> dict:
        """Cardiologist cross-examination review."""
        return _cardio_review_impl(topic, git_context=git_context or None, file_paths=file_paths)

    @_mcp_app.tool()
    def ab_validate_tool(description: str) -> dict:
        """Quick 3-surgeon fix validation."""
        return _ab_validate_impl(description)

    @_mcp_app.tool()
    def research_tool(topic: str) -> dict:
        """Self-directed research on a topic."""
        return _research_impl(topic)

    @_mcp_app.tool()
    def upgrade_probe() -> dict:
        """Probe ecosystem and report detected phase + available infrastructure."""
        return _upgrade_probe_impl()

    @_mcp_app.tool()
    def upgrade_history() -> str:
        """Show upgrade event log."""
        return _upgrade_history_impl()

    @_mcp_app.tool()
    def capability_status(
        verbose: bool = False,
        capability: str | None = None,
    ) -> dict:
        """Query per-capability levels and system posture."""
        return _capability_status(verbose=verbose, capability=capability)

    # ── Phase 3: IDE Event Bus tools ───────────────────────────────────

    @_mcp_app.tool()
    def event_subscribe(patterns: list[str]) -> dict:
        """Subscribe to event bus patterns. Returns stream_id for polling."""
        from three_surgeons.ide.event_bus import EventBus
        from three_surgeons.mcp.event_tools import event_subscribe as _subscribe
        return _subscribe(EventBus.get_instance(), patterns)

    @_mcp_app.tool()
    def event_unsubscribe(stream_id: str) -> dict:
        """Unsubscribe from an event stream by stream_id."""
        from three_surgeons.ide.event_bus import EventBus
        from three_surgeons.mcp.event_tools import event_unsubscribe as _unsubscribe
        return _unsubscribe(EventBus.get_instance(), stream_id)

    @_mcp_app.tool()
    def event_publish(event_type: str, payload: dict | None = None, correlation_id: str | None = None) -> dict:
        """Publish an event to the IDE event bus."""
        from three_surgeons.ide.event_bus import EventBus
        from three_surgeons.mcp.event_tools import event_publish as _publish
        return _publish(EventBus.get_instance(), event_type, payload, correlation_id)

    @_mcp_app.tool()
    def event_poll(stream_id: str) -> dict:
        """Poll for events on a subscription stream. Returns and clears queued events."""
        from three_surgeons.ide.event_bus import EventBus
        from three_surgeons.mcp.event_tools import event_poll as _poll
        return _poll(EventBus.get_instance(), stream_id)

except ImportError:
    # mcp SDK not installed -- tools are still usable as plain functions
    logger.info("mcp SDK not installed; MCP server will not start. Tools available as plain functions.")


# ── Convenience aliases ─────────────────────────────────────────────────

app = _mcp_app


def create_server() -> Optional[object]:
    """Return the FastMCP app if available, else None."""
    return _mcp_app


# ── __main__ entry point ────────────────────────────────────────────────

if __name__ == "__main__":
    if _mcp_app is not None:
        _mcp_app.run()
    else:
        print(
            "Error: mcp SDK not installed. "
            "Install with: pip install 'three-surgeons[mcp]'"
        )
        raise SystemExit(1)
