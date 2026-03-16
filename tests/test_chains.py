"""Tests for chain segment registry, executor, and state."""
from __future__ import annotations

import pytest

from three_surgeons.core.chains import (
    ChainSegment,
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
