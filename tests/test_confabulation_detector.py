"""Regression tests for the confabulation detector (RACE M2).

Two real regressions motivate this module: a surgeon-reviewer subagent twice
hallucinated unrelated kernel content (kernel PM callbacks, kernel param
baseline) when answering questions about the Context DNA webhook fix.

These tests pin the detector's behaviour so future surgeons can't silently
wander out of domain.
"""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from three_surgeons.core.confabulation_detector import (
    ConfabulationReport,
    detect_confabulation,
    known_domains,
)
from three_surgeons.core.cross_exam import SurgeryTeam
from three_surgeons.core.evidence import EvidenceStore
from three_surgeons.core.models import LLMResponse
from three_surgeons.core.state import MemoryBackend


# ── Detector heuristics ──────────────────────────────────────────────


class TestDetectorHeuristics:
    """Pure-function heuristics — no LLM, no state."""

    def test_known_good_answer_is_clean(self):
        question = "Why did the Context DNA webhook fix improve delivery?"
        answer = (
            "The webhook fix removed the duplicate signature header and "
            "fixed the HMAC payload encoding. After the fix, the endpoint "
            "returns 200 OK consistently and the retry policy no longer "
            "triggers."
        )
        report = detect_confabulation(question, answer)
        assert isinstance(report, ConfabulationReport)
        assert report.confabulated is False
        assert report.confidence < 0.5
        # Webhook signature terms appear only because the question is
        # in the webhook domain — they should NOT show up as foreign.
        assert not any(s.startswith("out_of_domain:webhook") for s in report.signals)

    def test_kernel_pm_hallucination_is_flagged(self):
        """The actual session regression: webhook question, kernel-PM answer."""
        question = "Why did the Context DNA webhook fix improve delivery?"
        answer = (
            "The fix re-registers the kernel PM callbacks so the PM domain "
            "wakes the device before the syscall hooks fire. Previously the "
            "kthread scheduler saw a stale kernel parameter baseline and "
            "the request_irq path never completed."
        )
        report = detect_confabulation(question, answer)
        assert report.confabulated is True
        assert report.confidence > 0.5
        # We expect both the domain signal AND specific jargon hits.
        assert any(s.startswith("out_of_domain:kernel") for s in report.signals)
        assert any(s.startswith("fabricated_jargon:") for s in report.signals)

    def test_kernel_param_baseline_hallucination_is_flagged(self):
        """Second observed regression — fabricated 'kernel param baseline'."""
        question = "What changed in the webhook fix commit?"
        answer = (
            "The commit restored the kernel parameter baseline that the "
            "previous PM callbacks had clobbered."
        )
        report = detect_confabulation(question, answer)
        assert report.confabulated is True
        assert any(
            "kernel param" in s or "fabricated_jargon" in s
            for s in report.signals
        )

    def test_borderline_unbacked_citation_flags_signal(self):
        """Borderline: citing a spec the question never named."""
        question = "Should we cache the webhook payload?"
        # No domain confab, but invents an authoritative source.
        answer = (
            "According to the IETF Webhook Caching specification, all "
            "payloads must be cached for at least 60 seconds. Per the "
            "OpenAPI Caching docs we should also set Vary headers."
        )
        report = detect_confabulation(question, answer)
        assert any(
            s.startswith("unbacked_citation:") for s in report.signals
        ), report.signals
        # Borderline: at least one signal even if confidence stays moderate.
        assert report.confidence > 0.0

    def test_empty_answer_is_clean(self):
        report = detect_confabulation("anything", "")
        assert report.confabulated is False
        assert report.confidence == 0.0
        assert report.signals == []

    def test_kernel_question_kernel_answer_not_flagged(self):
        """When the question IS about the kernel, kernel terms are fine."""
        question = "Walk me through the Linux kernel module's PM callbacks."
        answer = (
            "The kernel PM callbacks fire during suspend/resume. The PM "
            "domain framework dispatches them via syscall hooks."
        )
        report = detect_confabulation(question, answer)
        # Domain matches, so no out_of_domain signal.
        assert not any(s.startswith("out_of_domain:") for s in report.signals)

    def test_known_domains_includes_webhook_and_kernel(self):
        domains = set(known_domains())
        assert "webhook" in domains
        assert "kernel" in domains


# ── Pipeline integration ─────────────────────────────────────────────


def _make_team(tmp_path, cardio_text: str, neuro_text: str):
    cardio = MagicMock()
    cardio.query.return_value = LLMResponse(
        ok=True,
        content=cardio_text,
        latency_ms=100,
        model="gpt-4.1-mini",
        cost_usd=0.001,
    )
    neuro = MagicMock()
    neuro.query.return_value = LLMResponse(
        ok=True,
        content=neuro_text,
        latency_ms=50,
        model="qwen3:4b",
    )
    evidence = EvidenceStore(str(tmp_path / "evidence.db"))
    state = MemoryBackend()
    team = SurgeryTeam(
        cardiologist=cardio,
        neurologist=neuro,
        evidence=evidence,
        state=state,
    )
    return team, state


class TestPipelineIntegration:
    """End-to-end: confabulation gets surfaced through SurgeryTeam ops."""

    def test_consult_flags_confabulated_answer_and_increments_counter(self, tmp_path):
        kernel_pm_hallucination = (
            "The kernel PM callbacks fire when the syscall hooks dispatch. "
            "The kernel parameter baseline was reset by the PM domain."
        )
        clean_answer = (
            "The webhook fix corrected the HMAC signature header so the "
            "endpoint returns 200 OK reliably."
        )
        team, state = _make_team(
            tmp_path,
            cardio_text=kernel_pm_hallucination,
            neuro_text=clean_answer,
        )

        result = team.consult("Why did the Context DNA webhook fix improve delivery?")

        # The confabulated cardiologist answer must be flagged on the result.
        assert "cardiologist" in result.confabulation_flags
        assert result.confabulation_flags["cardiologist"]["confabulated"] is True

        # Clean neurologist answer should NOT be flagged.
        assert "neurologist" not in result.confabulation_flags

        # A warning must be appended for the operator.
        assert any(
            "Confabulation suspected" in w for w in result.warnings
        ), result.warnings

        # The counter must have ticked.
        assert state.get("confab:total_flagged") == "1"
        assert state.get("confab:by_surgeon:cardiologist") == "1"
        assert state.get("confab:by_surgeon:neurologist") is None

    def test_consult_clean_answers_do_not_flag(self, tmp_path):
        clean = (
            "The webhook fix corrected the HMAC signature so the endpoint "
            "returns 200 OK after retry."
        )
        team, state = _make_team(tmp_path, cardio_text=clean, neuro_text=clean)

        result = team.consult("Why did the webhook fix help?")

        assert result.confabulation_flags == {}
        assert not any("Confabulation suspected" in w for w in result.warnings)
        assert state.get("confab:total_flagged") is None

    def test_consensus_flags_confabulated_response(self, tmp_path):
        # Surgeons return JSON, but a confabulating model often pads with
        # off-topic prose around the JSON. We feed exactly that.
        confab_json = (
            '{"confidence": 0.9, "assessment": "agree", '
            '"reasoning": "kernel PM callbacks confirm this; '
            'the syscall hooks are well-known per RFC 9999"}'
        )
        clean_json = (
            '{"confidence": 0.6, "assessment": "agree", '
            '"reasoning": "the webhook signature header is correct"}'
        )
        team, state = _make_team(
            tmp_path,
            cardio_text=confab_json,
            neuro_text=clean_json,
        )

        result = team.consensus(
            "The Context DNA webhook fix resolves the delivery regression."
        )

        assert "cardiologist" in result.confabulation_flags
        assert state.get("confab:total_flagged") == "1"
        assert state.get("confab:by_surgeon:cardiologist") == "1"


# ── Confidence shape ─────────────────────────────────────────────────


class TestConfidenceShape:
    def test_confidence_is_clamped_to_unit_interval(self):
        """Many independent signals must not push score above 1.0."""
        question = "What changed in the webhook fix?"
        answer = (
            "The kernel PM callbacks, kernel param baseline, syscall hooks, "
            "PM domain, kthread scheduler, drm driver, and module_param() "
            "were all refactored. According to the Linux Kernel Driver "
            "specification (RFC 9999) these are required."
        )
        report = detect_confabulation(question, answer)
        assert 0.0 <= report.confidence <= 1.0
        assert report.confabulated is True

    @pytest.mark.parametrize("text", ["", "   ", "\n\n"])
    def test_blank_inputs_are_clean(self, text):
        report = detect_confabulation("question", text)
        assert report.confabulated is False
        assert report.confidence == 0.0
