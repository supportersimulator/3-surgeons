"""Tests for audit commands: research-evidence, cardio-reverify, deep-audit."""
from __future__ import annotations

import json
from unittest.mock import MagicMock

import pytest

from three_surgeons.core.requirements import CommandRequirements, CommandResult, RuntimeContext


def _make_ctx(healthy_llms=0, state=None, evidence=None, git=False, git_root=None):
    return RuntimeContext(
        healthy_llms=[MagicMock() for _ in range(healthy_llms)],
        state=state or MagicMock(),
        evidence=evidence or MagicMock(),
        git_available=git,
        git_root=git_root,
        config=MagicMock(),
    )


class TestCmdResearchEvidence:
    def test_import(self):
        from three_surgeons.core.audit_commands import cmd_research_evidence, RESEARCH_EVIDENCE_REQS
        assert callable(cmd_research_evidence)

    def test_requirements(self):
        from three_surgeons.core.audit_commands import RESEARCH_EVIDENCE_REQS
        assert RESEARCH_EVIDENCE_REQS.min_llms == 1
        assert RESEARCH_EVIDENCE_REQS.needs_state is True
        assert RESEARCH_EVIDENCE_REQS.needs_evidence is True
        assert RESEARCH_EVIDENCE_REQS.recommended_llms == 2

    def test_returns_evidence_analysis(self):
        from three_surgeons.core.audit_commands import cmd_research_evidence
        evidence = MagicMock()
        evidence.search.return_value = [
            {"topic": "caching", "observation": "Redis improved latency"},
            {"topic": "caching", "observation": "SQLite fallback works"},
        ]
        llm = MagicMock()
        llm.query.return_value = MagicMock(
            ok=True, content="Evidence supports caching approach", cost_usd=0.01
        )
        ctx = _make_ctx(healthy_llms=1, evidence=evidence)
        ctx.healthy_llms = [llm]
        result = cmd_research_evidence(ctx, topic="caching")
        assert result.success is True
        assert "analysis" in result.data
        assert result.data["evidence_count"] == 2

    def test_no_evidence_found(self):
        from three_surgeons.core.audit_commands import cmd_research_evidence
        evidence = MagicMock()
        evidence.search.return_value = []
        llm = MagicMock()
        ctx = _make_ctx(healthy_llms=1, evidence=evidence)
        ctx.healthy_llms = [llm]
        result = cmd_research_evidence(ctx, topic="nonexistent")
        assert result.success is True
        assert result.data["evidence_count"] == 0
