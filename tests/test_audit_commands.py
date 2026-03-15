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


class TestCmdCardioReverify:
    def test_import(self):
        from three_surgeons.core.audit_commands import cmd_cardio_reverify, CARDIO_REVERIFY_REQS
        assert callable(cmd_cardio_reverify)

    def test_requirements(self):
        from three_surgeons.core.audit_commands import CARDIO_REVERIFY_REQS
        assert CARDIO_REVERIFY_REQS.min_llms == 2
        assert CARDIO_REVERIFY_REQS.needs_git is True
        assert CARDIO_REVERIFY_REQS.recommended_llms == 3

    def test_reverify_success(self):
        from three_surgeons.core.audit_commands import cmd_cardio_reverify
        evidence = MagicMock()
        evidence.search.return_value = [
            {"topic": "caching", "observation": "works", "grade": "cohort"},
        ]
        llm1 = MagicMock()
        llm1.query.return_value = MagicMock(
            ok=True, content="Evidence still valid after code review", cost_usd=0.02
        )
        llm2 = MagicMock()
        llm2.query.return_value = MagicMock(
            ok=True, content="Confirmed, caching evidence holds", cost_usd=0.02
        )
        ctx = _make_ctx(healthy_llms=2, evidence=evidence, git=True, git_root="/repo")
        ctx.healthy_llms = [llm1, llm2]
        result = cmd_cardio_reverify(ctx, topic="caching")
        assert result.success is True
        assert "reverification" in result.data or "assessments" in result.data

    def test_reverify_blocked_no_git(self):
        from three_surgeons.core.audit_commands import CARDIO_REVERIFY_REQS
        from three_surgeons.core.requirements import GateResult, check_requirements
        ctx = _make_ctx(healthy_llms=2, git=False)
        gate, _ = check_requirements(CARDIO_REVERIFY_REQS, ctx)
        assert gate == GateResult.BLOCKED
