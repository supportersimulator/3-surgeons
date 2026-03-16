"""Integration test — register segments, run chain, verify telemetry."""
from __future__ import annotations

import pytest

from three_surgeons.core.chains import (
    ChainExecutor,
    ChainSegment,
    SEGMENT_REGISTRY,
    segment,
)
from three_surgeons.core.chain_telemetry import ChainTelemetry
from three_surgeons.core.mode_authority import ModeAuthority, PRESETS
from three_surgeons.core.requirements import (
    CommandRequirements,
    CommandResult,
    RuntimeContext,
)
from three_surgeons.core.state import MemoryBackend


@pytest.fixture(autouse=True)
def _clean_registry():
    saved = dict(SEGMENT_REGISTRY)
    SEGMENT_REGISTRY.clear()
    yield
    SEGMENT_REGISTRY.clear()
    SEGMENT_REGISTRY.update(saved)


TRIVIAL = CommandRequirements(min_llms=0)


def _make_ctx(state=None):
    return RuntimeContext(
        healthy_llms=[],
        state=state or MemoryBackend(),
        evidence=None,
        git_available=False,
        git_root=None,
        config=None,
    )


def test_full_chain_lifecycle():
    """Register segments -> resolve preset -> execute chain -> check telemetry."""

    # Register lightweight segments
    @segment("pre-flight", requires=TRIVIAL, tags={"setup"})
    def seg_preflight(ctx, state):
        state["preflight_done"] = True
        return CommandResult(success=True, data={"preflight_done": True})

    @segment("execute", requires=TRIVIAL, tags={"core"})
    def seg_execute(ctx, state):
        assert state.get("preflight_done"), "pre-flight should have run"
        return CommandResult(success=True, data={"executed": True})

    @segment("verify", requires=TRIVIAL, tags={"check"})
    def seg_verify(ctx, state):
        assert state.get("executed"), "execute should have run"
        return CommandResult(success=True, data={"verified": True})

    state = MemoryBackend()
    ctx = _make_ctx(state)

    # Resolve preset
    ma = ModeAuthority(state)
    segments = ma.resolve("lightweight", {})
    assert segments == ["pre-flight", "execute", "verify"]

    # Execute chain
    executor = ChainExecutor(state_backend=state)
    result = executor.run(segments, ctx)

    assert not result.halted
    assert len(result.errors) == 0
    assert result.data["preflight_done"] is True
    assert result.data["executed"] is True
    assert result.data["verified"] is True
    assert len(result.segment_results) == 3

    # Check telemetry was recorded
    raw = state.list_range("chain:executions", 0, 0)
    assert len(raw) == 1


def test_mixed_gate_results():
    """Some segments blocked, some degraded, some proceed."""

    @segment("always-run", requires=TRIVIAL)
    def seg_always(ctx, state):
        return CommandResult(success=True, data={"always": True})

    @segment("needs-llm", requires=CommandRequirements(min_llms=1))
    def seg_needs_llm(ctx, state):
        return CommandResult(success=True, data={"llm_ran": True})

    @segment("wants-more", requires=CommandRequirements(min_llms=0, recommended_llms=3))
    def seg_wants_more(ctx, state):
        return CommandResult(success=True, data={"ran_degraded": True})

    state = MemoryBackend()
    ctx = _make_ctx(state)  # 0 LLMs

    executor = ChainExecutor(state_backend=state)
    result = executor.run(["always-run", "needs-llm", "wants-more"], ctx)

    assert result.data.get("always") is True
    assert "llm_ran" not in result.data  # blocked
    assert result.data.get("ran_degraded") is True  # degraded but ran
    assert len(result.skipped) == 1
    assert len(result.degraded) == 1
