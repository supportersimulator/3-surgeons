"""Tests for research and evidence cross-examination commands."""
from __future__ import annotations

import json
from unittest.mock import MagicMock

import pytest

from three_surgeons.core.research import (
    BudgetTracker,
    EvidenceCrossExamResult,
    EvidenceVerdict,
    ResearchResult,
    cross_examine_evidence,
    research,
    _parse_research,
    _parse_verdicts,
)
from three_surgeons.core.state import MemoryBackend


# ── Dataclasses ──────────────────────────────────────────────────────


class TestResearchResult:
    def test_fields(self):
        rr = ResearchResult(
            topic="auth patterns",
            findings=["finding1"],
            sources=["file.py"],
            cost_usd=0.01,
            raw_response="raw",
        )
        assert rr.topic == "auth patterns"
        assert len(rr.findings) == 1
        assert rr.cost_usd == 0.01


class TestEvidenceVerdict:
    def test_fields(self):
        ev = EvidenceVerdict(
            claim="Auth is secure",
            verdict="TRUE_TO_EVIDENCE",
            confidence=0.9,
            reasoning="Multiple sources confirm",
        )
        assert ev.verdict == "TRUE_TO_EVIDENCE"
        assert ev.confidence == 0.9


class TestEvidenceCrossExamResult:
    def test_fields(self):
        ecr = EvidenceCrossExamResult(
            topic="auth",
            verdicts=[EvidenceVerdict("claim", "WORTH_TESTING", 0.6, "reason")],
            ab_test_candidates=["claim"],
            cost_usd=0.005,
        )
        assert len(ecr.verdicts) == 1
        assert len(ecr.ab_test_candidates) == 1


# ── BudgetTracker ────────────────────────────────────────────────────


class TestBudgetTracker:
    def test_initial_spend_zero(self):
        state = MemoryBackend()
        tracker = BudgetTracker(state, daily_limit_usd=5.0)
        assert tracker.spent_today() == 0.0

    def test_remaining_equals_limit(self):
        state = MemoryBackend()
        tracker = BudgetTracker(state, daily_limit_usd=5.0)
        assert tracker.remaining() == 5.0

    def test_track_reduces_remaining(self):
        state = MemoryBackend()
        tracker = BudgetTracker(state, daily_limit_usd=5.0)
        tracker.track(1.5, "test query")
        assert tracker.spent_today() == 1.5
        assert tracker.remaining() == 3.5

    def test_can_afford_true(self):
        state = MemoryBackend()
        tracker = BudgetTracker(state, daily_limit_usd=5.0)
        assert tracker.can_afford(4.0) is True

    def test_can_afford_false(self):
        state = MemoryBackend()
        tracker = BudgetTracker(state, daily_limit_usd=5.0)
        tracker.track(4.5)
        assert tracker.can_afford(1.0) is False

    def test_multiple_tracks_accumulate(self):
        state = MemoryBackend()
        tracker = BudgetTracker(state, daily_limit_usd=10.0)
        tracker.track(2.0)
        tracker.track(3.0)
        tracker.track(1.5)
        assert tracker.spent_today() == 6.5
        assert tracker.remaining() == 3.5

    def test_remaining_never_negative(self):
        state = MemoryBackend()
        tracker = BudgetTracker(state, daily_limit_usd=1.0)
        tracker.track(5.0)
        assert tracker.remaining() == 0.0


# ── research ─────────────────────────────────────────────────────────


class TestResearch:
    def test_basic_research(self):
        provider = MagicMock()
        resp = MagicMock()
        resp.ok = True
        resp.content = json.dumps({
            "findings": ["Auth uses JWT", "No MFA"],
            "sources": ["auth.py"],
        })
        resp.cost_usd = 0.01
        provider.query.return_value = resp
        result = research("auth patterns", provider)
        assert isinstance(result, ResearchResult)
        assert len(result.findings) == 2
        assert result.cost_usd == 0.01

    def test_with_file_index(self):
        provider = MagicMock()
        resp = MagicMock()
        resp.ok = True
        resp.content = json.dumps({"findings": ["found"], "sources": []})
        resp.cost_usd = 0.005
        provider.query.return_value = resp
        file_index = [
            {"path": "auth.py", "summary": "Authentication module"},
            {"path": "db.py", "summary": "Database models"},
        ]
        result = research("auth", provider, file_index=file_index)
        assert len(result.findings) == 1

    def test_provider_error(self):
        provider = MagicMock()
        provider.query.side_effect = RuntimeError("LLM down")
        result = research("topic", provider)
        assert result.findings == []
        assert result.cost_usd == 0.0

    def test_failed_response(self):
        provider = MagicMock()
        resp = MagicMock()
        resp.ok = False
        resp.content = "Error"
        resp.cost_usd = 0
        provider.query.return_value = resp
        result = research("topic", provider)
        assert result.findings == []


# ── cross_examine_evidence ───────────────────────────────────────────


class TestCrossExamineEvidence:
    def test_basic_cross_exam(self):
        provider = MagicMock()
        resp = MagicMock()
        resp.ok = True
        resp.content = json.dumps({
            "verdicts": [
                {"claim": "Auth is secure", "verdict": "TRUE_TO_EVIDENCE",
                 "confidence": 0.9, "reasoning": "Confirmed"},
                {"claim": "No rate limiting", "verdict": "WORTH_TESTING",
                 "confidence": 0.6, "reasoning": "Should verify"},
            ]
        })
        resp.cost_usd = 0.02
        provider.query.return_value = resp
        evidence_store = MagicMock()
        evidence_store.get_evidence_snapshot.return_value = {"evidence_text": "some evidence"}
        result = cross_examine_evidence("auth security", provider, evidence_store)
        assert isinstance(result, EvidenceCrossExamResult)
        assert len(result.verdicts) == 2
        assert len(result.ab_test_candidates) == 1
        assert result.ab_test_candidates[0] == "No rate limiting"

    def test_evidence_store_error(self):
        provider = MagicMock()
        resp = MagicMock()
        resp.ok = True
        resp.content = json.dumps({"verdicts": []})
        resp.cost_usd = 0
        provider.query.return_value = resp
        evidence_store = MagicMock()
        evidence_store.get_evidence_snapshot.side_effect = RuntimeError("DB error")
        result = cross_examine_evidence("topic", provider, evidence_store)
        assert isinstance(result, EvidenceCrossExamResult)

    def test_provider_error(self):
        provider = MagicMock()
        provider.query.side_effect = RuntimeError("down")
        evidence_store = MagicMock()
        evidence_store.get_evidence_snapshot.return_value = {"evidence_text": ""}
        result = cross_examine_evidence("topic", provider, evidence_store)
        assert len(result.verdicts) == 0


# ── _parse_research ──────────────────────────────────────────────────


class TestParseResearch:
    def test_valid_json(self):
        raw = json.dumps({"findings": ["a", "b"], "sources": ["x.py"]})
        findings, sources = _parse_research(raw)
        assert findings == ["a", "b"]
        assert sources == ["x.py"]

    def test_empty_string(self):
        findings, sources = _parse_research("")
        assert findings == []
        assert sources == []

    def test_invalid_json(self):
        findings, sources = _parse_research("not json at all")
        assert len(findings) == 1
        assert sources == []

    def test_json_with_surrounding_text(self):
        raw = 'Here: {"findings": ["found"], "sources": []} end'
        findings, sources = _parse_research(raw)
        assert findings == ["found"]


# ── _parse_verdicts ──────────────────────────────────────────────────


class TestParseVerdicts:
    def test_valid_json(self):
        raw = json.dumps({
            "verdicts": [
                {"claim": "X", "verdict": "TRUE_TO_EVIDENCE", "confidence": 0.9, "reasoning": "yes"},
            ]
        })
        verdicts = _parse_verdicts(raw)
        assert len(verdicts) == 1
        assert verdicts[0].verdict == "TRUE_TO_EVIDENCE"

    def test_empty_string(self):
        assert _parse_verdicts("") == []

    def test_invalid_json(self):
        assert _parse_verdicts("not json") == []

    def test_missing_fields_use_defaults(self):
        raw = json.dumps({"verdicts": [{"claim": "X"}]})
        verdicts = _parse_verdicts(raw)
        assert verdicts[0].verdict == "NO_EVIDENCE"
        assert verdicts[0].confidence == 0.5
