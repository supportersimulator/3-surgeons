"""MCP server exposing 3-Surgeons core/ as typed tools.

Thin wrapper -- each tool delegates to the same core functions as the CLI.
Uses the FastMCP pattern from the `mcp` Python SDK when available.
Falls back to plain function definitions when the SDK is not installed,
keeping the module importable for testing and discoverability.

Run: python -m three_surgeons.mcp.server
"""
from __future__ import annotations

import logging
from typing import Optional

from three_surgeons.core.ab_testing import ABTestEngine
from three_surgeons.core.config import Config
from three_surgeons.core.cross_exam import SurgeryTeam
from three_surgeons.core.evidence import EvidenceStore
from three_surgeons.core.gates import GainsGate
from three_surgeons.core.models import LLMProvider
from three_surgeons.core.sentinel import Sentinel
from three_surgeons.core.state import MemoryBackend

logger = logging.getLogger(__name__)

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
    neuro = LLMProvider(config.neurologist)
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


def _cross_examine(topic: str, depth: str = "full") -> dict:
    """Full cross-examination protocol."""
    team = _build_surgery_team()
    result = team.cross_examine(topic, depth=depth)
    return {
        "topic": result.topic,
        "cardiologist_report": result.cardiologist_report,
        "neurologist_report": result.neurologist_report,
        "synthesis": result.synthesis,
        "total_cost": result.total_cost,
        "total_latency_ms": result.total_latency_ms,
    }


def _consult(topic: str) -> dict:
    """Quick consult with both surgeons."""
    team = _build_surgery_team()
    result = team.consult(topic)
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
    def cross_examine(topic: str, depth: str = "full") -> dict:
        """Full cross-examination protocol."""
        return _cross_examine(topic, depth=depth)

    @_mcp_app.tool()
    def consult(topic: str) -> dict:
        """Quick consult with both surgeons."""
        return _consult(topic)

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
