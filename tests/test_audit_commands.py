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


class TestCmdDeepAudit:
    def test_import(self):
        from three_surgeons.core.audit_commands import cmd_deep_audit, DEEP_AUDIT_REQS
        assert callable(cmd_deep_audit)

    def test_requirements(self):
        from three_surgeons.core.audit_commands import DEEP_AUDIT_REQS
        assert DEEP_AUDIT_REQS.min_llms == 1
        assert DEEP_AUDIT_REQS.needs_git is True
        assert DEEP_AUDIT_REQS.recommended_llms == 3

    def test_deep_audit_success(self):
        from three_surgeons.core.audit_commands import cmd_deep_audit

        phase3_json = json.dumps({
            "planned_items": [
                {"name": "Cache layer", "description": "Add Redis cache",
                 "source_file": "docs/plan.md", "status": "PLANNED",
                 "category": "infrastructure", "priority": "high",
                 "implementation_hints": "Use Redis"}
            ],
            "total_items": 1,
            "summary": "One planned feature"
        })
        phase4_json = json.dumps({
            "gap_analysis": [
                {"name": "Cache layer", "verdict": "NOT_BUILT",
                 "evidence": "No evidence found", "confidence": 0.8,
                 "priority": "high", "recommendation": "Implement cache"}
            ],
            "ab_test_candidates": [],
            "summary": {"total_planned": 1, "built": 0, "not_built": 1,
                        "partially_built": 0, "uncertain": 0,
                        "narrative": "One gap found"}
        })

        evidence = MagicMock()
        evidence.search.return_value = []
        llm = MagicMock()
        llm.query.side_effect = [
            MagicMock(ok=True, content=phase3_json, cost_usd=0.03),
            MagicMock(ok=True, content=phase4_json, cost_usd=0.02),
        ]
        ctx = _make_ctx(healthy_llms=1, evidence=evidence, git=True, git_root="/repo")
        ctx.healthy_llms = [llm]

        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(
                "three_surgeons.core.audit_commands._read_files",
                lambda *a, **kw: {"docs/plan.md": "# Plan\n## Cache layer\nAdd Redis cache."},
            )
            result = cmd_deep_audit(
                ctx, topic="architecture review",
                file_paths=["docs/plan.md"],
            )

        assert result.success is True
        assert "phases" in result.data

    def test_deep_audit_blocked_no_git(self):
        from three_surgeons.core.audit_commands import DEEP_AUDIT_REQS
        from three_surgeons.core.requirements import GateResult, check_requirements
        ctx = _make_ctx(healthy_llms=1, git=False)
        gate, _ = check_requirements(DEEP_AUDIT_REQS, ctx)
        assert gate == GateResult.BLOCKED

    def test_deep_audit_degraded_one_llm(self):
        from three_surgeons.core.audit_commands import cmd_deep_audit

        phase3_json = json.dumps({
            "planned_items": [], "total_items": 0, "summary": "Nothing found"
        })

        evidence = MagicMock()
        evidence.search.return_value = []
        llm = MagicMock()
        # Phase 3 only (Phase 4 skipped when no planned_items and no evidence)
        llm.query.return_value = MagicMock(
            ok=True, content=phase3_json, cost_usd=0.03
        )
        ctx = _make_ctx(healthy_llms=1, evidence=evidence, git=True, git_root="/repo")
        ctx.healthy_llms = [llm]

        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(
                "three_surgeons.core.audit_commands._read_files",
                lambda *a, **kw: {"src/main.py": "def main(): pass"},
            )
            result = cmd_deep_audit(
                ctx, topic="test", file_paths=["src/main.py"]
            )

        assert result.degraded is True
        assert any("surgeon" in n.lower() for n in result.degradation_notes)
