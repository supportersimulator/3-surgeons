"""Tests for A/B lifecycle commands."""
from __future__ import annotations

import json
import time
from unittest.mock import MagicMock

import pytest

from three_surgeons.core.requirements import CommandRequirements, CommandResult, RuntimeContext


def _make_ctx(healthy_llms=0, state=None, evidence=None, precondition_checker=None):
    return RuntimeContext(
        healthy_llms=[MagicMock() for _ in range(healthy_llms)],
        state=state or MagicMock(),
        evidence=evidence or MagicMock(),
        git_available=False,
        git_root=None,
        config=MagicMock(),
        precondition_checker=precondition_checker,
    )


class TestCmdAbVeto:
    def test_import(self):
        from three_surgeons.core.ab_lifecycle import cmd_ab_veto, AB_VETO_REQS
        assert callable(cmd_ab_veto)

    def test_requirements(self):
        from three_surgeons.core.ab_lifecycle import AB_VETO_REQS
        assert AB_VETO_REQS.min_llms == 0
        assert AB_VETO_REQS.needs_state is True
        assert AB_VETO_REQS.preconditions == ["ab_test_exists"]

    def test_veto_updates_state(self):
        from three_surgeons.core.ab_lifecycle import cmd_ab_veto
        state = MagicMock()
        test_data = {"id": "test-1", "status": "active", "param": "x", "hypothesis": "h"}
        state.get.return_value = json.dumps(test_data)
        ctx = _make_ctx(state=state)
        result = cmd_ab_veto(ctx, test_id="test-1", reason="Too risky")
        assert result.success is True
        assert result.data["vetoed_id"] == "test-1"
        state.set.assert_called()

    def test_veto_missing_test(self):
        from three_surgeons.core.ab_lifecycle import cmd_ab_veto
        state = MagicMock()
        state.get.return_value = None
        ctx = _make_ctx(state=state)
        result = cmd_ab_veto(ctx, test_id="nonexistent", reason="nope")
        assert result.blocked is True


class TestCmdAbQueue:
    def test_import(self):
        from three_surgeons.core.ab_lifecycle import cmd_ab_queue, AB_QUEUE_REQS
        assert callable(cmd_ab_queue)

    def test_requirements(self):
        from three_surgeons.core.ab_lifecycle import AB_QUEUE_REQS
        assert AB_QUEUE_REQS.min_llms == 0
        assert AB_QUEUE_REQS.needs_state is True

    def test_returns_queue_list(self):
        from three_surgeons.core.ab_lifecycle import cmd_ab_queue
        state = MagicMock()
        state.list_range.return_value = [
            json.dumps({"id": "t1", "status": "proposed"}),
            json.dumps({"id": "t2", "status": "active"}),
        ]
        ctx = _make_ctx(state=state)
        result = cmd_ab_queue(ctx)
        assert result.success is True
        assert len(result.data["tests"]) == 2

    def test_empty_queue(self):
        from three_surgeons.core.ab_lifecycle import cmd_ab_queue
        state = MagicMock()
        state.list_range.return_value = []
        ctx = _make_ctx(state=state)
        result = cmd_ab_queue(ctx)
        assert result.success is True
        assert result.data["tests"] == []


class TestCmdAbStart:
    def test_import(self):
        from three_surgeons.core.ab_lifecycle import cmd_ab_start, AB_START_REQS
        assert callable(cmd_ab_start)

    def test_requirements(self):
        from three_surgeons.core.ab_lifecycle import AB_START_REQS
        assert AB_START_REQS.min_llms == 1
        assert AB_START_REQS.needs_state is True
        assert AB_START_REQS.needs_evidence is True
        assert AB_START_REQS.preconditions == ["ab_test_proposed"]

    def test_start_transitions_to_active(self):
        from three_surgeons.core.ab_lifecycle import cmd_ab_start
        state = MagicMock()
        test_data = {
            "id": "test-1", "status": "proposed", "param": "x",
            "variant_a": "old", "variant_b": "new", "hypothesis": "h",
        }
        state.get.return_value = json.dumps(test_data)
        evidence = MagicMock()
        llm = MagicMock()
        llm.query.return_value = MagicMock(ok=True, content="Grace period validated", cost_usd=0.01)
        ctx = _make_ctx(healthy_llms=1, state=state, evidence=evidence)
        result = cmd_ab_start(ctx, test_id="test-1", duration_minutes=30)
        assert result.success is True
        assert result.data["status"] == "active"
        state.set.assert_called()

    def test_start_missing_test(self):
        from three_surgeons.core.ab_lifecycle import cmd_ab_start
        state = MagicMock()
        state.get.return_value = None
        ctx = _make_ctx(healthy_llms=1, state=state)
        result = cmd_ab_start(ctx, test_id="nope")
        assert result.blocked is True
