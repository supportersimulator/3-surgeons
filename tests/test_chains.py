"""Tests for chain segment registry, executor, and state."""
from __future__ import annotations

import pytest

from three_surgeons.core.chains import (
    ChainSegment,
    ChainState,
    ChainExecutor,
    SEGMENT_REGISTRY,
    segment,
)
from three_surgeons.core.requirements import (
    CommandRequirements,
    CommandResult,
    RuntimeContext,
)
from three_surgeons.core.state import MemoryBackend


@pytest.fixture(autouse=True)
def _clean_registry():
    """Clear registry between tests to avoid cross-test pollution."""
    saved = dict(SEGMENT_REGISTRY)
    SEGMENT_REGISTRY.clear()
    yield
    SEGMENT_REGISTRY.clear()
    SEGMENT_REGISTRY.update(saved)


# -- Segment decorator & registry -----------------------------------------

TRIVIAL_REQS = CommandRequirements(min_llms=0)


def test_segment_decorator_registers():
    @segment("test-seg", requires=TRIVIAL_REQS, tags={"test"})
    def my_seg(ctx: RuntimeContext, state: dict) -> CommandResult:
        return CommandResult(success=True, data={"ran": True})

    assert "test-seg" in SEGMENT_REGISTRY
    seg = SEGMENT_REGISTRY["test-seg"]
    assert seg.name == "test-seg"
    assert seg.tags == {"test"}
    assert seg.requires is TRIVIAL_REQS


def test_segment_decorator_preserves_function():
    @segment("preserve-test", requires=TRIVIAL_REQS)
    def my_seg(ctx: RuntimeContext, state: dict) -> CommandResult:
        return CommandResult(success=True, data={"value": 42})

    seg = SEGMENT_REGISTRY["preserve-test"]
    ctx = _make_ctx()
    result = seg.fn(ctx, {})
    assert result.success
    assert result.data["value"] == 42


def test_duplicate_segment_name_raises():
    @segment("dup", requires=TRIVIAL_REQS)
    def seg_a(ctx, state):
        return CommandResult(success=True, data={})

    with pytest.raises(ValueError, match="already registered"):
        @segment("dup", requires=TRIVIAL_REQS)
        def seg_b(ctx, state):
            return CommandResult(success=True, data={})


# ── ChainState ────────────────────────────────────────────────────────

def test_chain_state_initial():
    cs = ChainState(data={"seed": 1})
    assert cs.data == {"seed": 1}
    assert cs.skipped == []
    assert cs.degraded == []
    assert cs.segment_results == {}
    assert cs.errors == []
    assert not cs.halted


# ── ChainExecutor ────────────────────────────────────────────────────

def test_executor_runs_segments_in_order():
    @segment("exec-a", requires=TRIVIAL_REQS)
    def seg_a(ctx, state):
        state["order"] = state.get("order", []) + ["a"]
        return CommandResult(success=True, data={"order": state["order"]})

    @segment("exec-b", requires=TRIVIAL_REQS)
    def seg_b(ctx, state):
        state["order"] = state.get("order", []) + ["b"]
        return CommandResult(success=True, data={"order": state["order"]})

    executor = ChainExecutor(state_backend=MemoryBackend())
    result = executor.run(["exec-a", "exec-b"], _make_ctx())

    assert not result.halted
    assert result.data["order"] == ["a", "b"]
    assert "exec-a" in result.segment_results
    assert "exec-b" in result.segment_results
    assert result.total_ns > 0


def test_executor_skips_blocked_segments():
    blocked_reqs = CommandRequirements(min_llms=5)  # Will always block

    @segment("will-block", requires=blocked_reqs)
    def seg_blocked(ctx, state):
        return CommandResult(success=True, data={"should_not_run": True})

    @segment("will-run", requires=TRIVIAL_REQS)
    def seg_ok(ctx, state):
        return CommandResult(success=True, data={"ran": True})

    executor = ChainExecutor(state_backend=MemoryBackend())
    result = executor.run(["will-block", "will-run"], _make_ctx())

    assert len(result.skipped) == 1
    assert result.skipped[0][0] == "will-block"
    assert result.data.get("ran") is True
    assert "should_not_run" not in result.data


def test_executor_records_degraded():
    degraded_reqs = CommandRequirements(min_llms=0, recommended_llms=3)

    @segment("soft-warn", requires=degraded_reqs)
    def seg_warn(ctx, state):
        return CommandResult(success=True, data={"ok": True})

    executor = ChainExecutor(state_backend=MemoryBackend())
    result = executor.run(["soft-warn"], _make_ctx())

    assert len(result.degraded) == 1
    assert result.degraded[0][0] == "soft-warn"


def test_executor_halts_on_error_when_configured():
    @segment("will-fail", requires=TRIVIAL_REQS)
    def seg_fail(ctx, state):
        raise RuntimeError("boom")

    @segment("after-fail", requires=TRIVIAL_REQS)
    def seg_after(ctx, state):
        return CommandResult(success=True, data={"reached": True})

    executor = ChainExecutor(state_backend=MemoryBackend(), halt_on_error=True)
    result = executor.run(["will-fail", "after-fail"], _make_ctx())

    assert result.halted
    assert "boom" in result.halt_reason
    assert len(result.errors) == 1
    assert "reached" not in result.data


def test_executor_continues_on_error_by_default():
    @segment("err-continue", requires=TRIVIAL_REQS)
    def seg_err(ctx, state):
        raise RuntimeError("oops")

    @segment("after-err", requires=TRIVIAL_REQS)
    def seg_after(ctx, state):
        return CommandResult(success=True, data={"reached": True})

    executor = ChainExecutor(state_backend=MemoryBackend())
    result = executor.run(["err-continue", "after-err"], _make_ctx())

    assert not result.halted
    assert len(result.errors) == 1
    assert result.data.get("reached") is True


def test_executor_accumulates_data_forward():
    @segment("produce", requires=TRIVIAL_REQS)
    def seg_produce(ctx, state):
        return CommandResult(success=True, data={"artifact": "value"})

    @segment("consume", requires=TRIVIAL_REQS)
    def seg_consume(ctx, state):
        got = state.get("artifact", "missing")
        return CommandResult(success=True, data={"consumed": got})

    executor = ChainExecutor(state_backend=MemoryBackend())
    result = executor.run(["produce", "consume"], _make_ctx())

    assert result.data["consumed"] == "value"


def test_executor_unknown_segment_raises():
    executor = ChainExecutor(state_backend=MemoryBackend())
    with pytest.raises(KeyError):
        executor.run(["nonexistent-segment"], _make_ctx())


# -- Helper ----------------------------------------------------------------

def _make_ctx(healthy_llms=None, state=None) -> RuntimeContext:
    return RuntimeContext(
        healthy_llms=healthy_llms or [],
        state=state or MemoryBackend(),
        evidence=None,
        git_available=False,
        git_root=None,
        config=None,
    )
