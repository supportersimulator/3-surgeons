"""Tests for status and research-status commands."""
from __future__ import annotations

import json
from unittest.mock import MagicMock

import pytest

from three_surgeons.core.requirements import CommandRequirements, CommandResult, RuntimeContext


def _make_ctx(healthy_llms=0, state=None, evidence=None):
    """Build a minimal RuntimeContext."""
    return RuntimeContext(
        healthy_llms=[MagicMock() for _ in range(healthy_llms)],
        state=state or MagicMock(),
        evidence=evidence or MagicMock(),
        git_available=False,
        git_root=None,
        config=MagicMock(),
    )


class TestCmdStatus:
    def test_import(self):
        from three_surgeons.core.status_commands import cmd_status, STATUS_REQS
        assert callable(cmd_status)
        assert isinstance(STATUS_REQS, CommandRequirements)

    def test_requirements(self):
        from three_surgeons.core.status_commands import STATUS_REQS
        assert STATUS_REQS.min_llms == 0
        assert STATUS_REQS.needs_state is True
        assert STATUS_REQS.needs_evidence is False
        assert STATUS_REQS.needs_git is False

    def test_returns_command_result(self):
        from three_surgeons.core.status_commands import cmd_status
        state = MagicMock()
        state.get.return_value = None
        ctx = _make_ctx(state=state)
        result = cmd_status(ctx)
        assert isinstance(result, CommandResult)
        assert result.success is True
        assert "surgeons" in result.data

    def test_reports_healthy_llm_count(self):
        from three_surgeons.core.status_commands import cmd_status
        state = MagicMock()
        state.get.return_value = None
        ctx = _make_ctx(healthy_llms=2, state=state)
        result = cmd_status(ctx)
        assert result.data["surgeons"]["healthy_count"] == 2

    def test_reads_state_keys(self):
        from three_surgeons.core.status_commands import cmd_status
        state = MagicMock()
        state.get.side_effect = lambda k: json.dumps({"test": True}) if k == "ab_test:active" else None
        ctx = _make_ctx(state=state)
        result = cmd_status(ctx)
        assert result.success is True


class TestCmdResearchStatus:
    def test_import(self):
        from three_surgeons.core.status_commands import cmd_research_status, RESEARCH_STATUS_REQS
        assert callable(cmd_research_status)
        assert isinstance(RESEARCH_STATUS_REQS, CommandRequirements)

    def test_requirements(self):
        from three_surgeons.core.status_commands import RESEARCH_STATUS_REQS
        assert RESEARCH_STATUS_REQS.min_llms == 0
        assert RESEARCH_STATUS_REQS.needs_state is True
        assert RESEARCH_STATUS_REQS.needs_evidence is True

    def test_returns_command_result(self):
        from three_surgeons.core.status_commands import cmd_research_status
        state = MagicMock()
        state.get.return_value = None
        state.list_range.return_value = []
        evidence = MagicMock()
        evidence.search.return_value = []
        ctx = _make_ctx(state=state, evidence=evidence)
        result = cmd_research_status(ctx)
        assert isinstance(result, CommandResult)
        assert result.success is True
        assert "budget" in result.data

    def test_reads_costs(self):
        from three_surgeons.core.status_commands import cmd_research_status
        state = MagicMock()
        state.get.return_value = json.dumps({"daily_usd": 5.0})
        state.list_range.return_value = [
            json.dumps({"date": "2026-03-14", "usd": 0.42}),
        ]
        evidence = MagicMock()
        evidence.search.return_value = []
        ctx = _make_ctx(state=state, evidence=evidence)
        result = cmd_research_status(ctx)
        assert result.data["budget"] == {"daily_usd": 5.0}
        assert len(result.data["recent_costs"]) == 1
