"""Tests for neurologist commands: pulse, challenge, introspect."""
from __future__ import annotations

import json
import os
from unittest.mock import MagicMock, patch

import pytest

from three_surgeons.core.neurologist import (
    Challenge,
    ChallengeResult,
    CheckDetail,
    IntrospectResult,
    PulseResult,
    introspect,
    neurologist_challenge,
    neurologist_pulse,
    _parse_challenges,
)
from three_surgeons.core.state import MemoryBackend
from three_surgeons.core.evidence import EvidenceStore


# ── Dataclasses ──────────────────────────────────────────────────────


class TestCheckDetail:
    def test_fields(self):
        cd = CheckDetail(ok=True, detail="OK", latency_ms=1.5)
        assert cd.ok is True
        assert cd.detail == "OK"
        assert cd.latency_ms == 1.5

    def test_default_latency(self):
        cd = CheckDetail(ok=True, detail="OK")
        assert cd.latency_ms == 0.0


class TestPulseResult:
    def test_fields(self):
        pr = PulseResult(
            healthy=True,
            checks={"llm": CheckDetail(ok=True, detail="OK")},
            summary="All healthy",
        )
        assert pr.healthy is True
        assert "llm" in pr.checks
        assert pr.summary == "All healthy"


class TestChallenge:
    def test_fields(self):
        c = Challenge(
            claim="Auth is secure",
            challenge="Token rotation missing",
            severity="critical",
            suggested_test="Check token expiry",
        )
        assert c.claim == "Auth is secure"
        assert c.severity == "critical"
        assert c.suggested_test == "Check token expiry"

    def test_default_suggested_test(self):
        c = Challenge(claim="X", challenge="Y", severity="informational")
        assert c.suggested_test is None


class TestChallengeResult:
    def test_fields(self):
        cr = ChallengeResult(
            topic="auth",
            challenges=[Challenge(claim="X", challenge="Y", severity="critical")],
            raw_response="raw",
        )
        assert cr.topic == "auth"
        assert len(cr.challenges) == 1


class TestIntrospectResult:
    def test_fields(self):
        ir = IntrospectResult(
            model="qwen3:4b",
            capabilities="Pattern matching",
            limitations="Small context",
            latency_ms=50.0,
            ok=True,
        )
        assert ir.model == "qwen3:4b"
        assert ir.ok is True

    def test_defaults(self):
        ir = IntrospectResult(model="x", capabilities="", limitations="")
        assert ir.latency_ms == 0.0
        assert ir.ok is True


# ── neurologist_pulse ────────────────────────────────────────────────


class TestNeurologistPulse:
    def test_healthy_llm(self):
        provider = MagicMock()
        resp = MagicMock()
        resp.ok = True
        provider.ping.return_value = resp
        result = neurologist_pulse(provider)
        assert result.healthy is True
        assert "llm_health" in result.checks

    def test_unhealthy_llm(self):
        provider = MagicMock()
        resp = MagicMock()
        resp.ok = False
        provider.ping.return_value = resp
        result = neurologist_pulse(provider)
        assert result.healthy is False
        assert result.checks["llm_health"].ok is False

    def test_unreachable_llm(self):
        provider = MagicMock()
        provider.ping.side_effect = ConnectionError("refused")
        result = neurologist_pulse(provider)
        assert result.healthy is False
        assert "unreachable" in result.checks["llm_health"].detail.lower()

    def test_state_backend_check(self):
        provider = MagicMock()
        resp = MagicMock()
        resp.ok = True
        provider.ping.return_value = resp
        state = MemoryBackend()
        result = neurologist_pulse(provider, state_backend=state)
        assert "state_backend" in result.checks
        assert result.checks["state_backend"].ok is True

    def test_evidence_store_check(self, tmp_path):
        provider = MagicMock()
        resp = MagicMock()
        resp.ok = True
        provider.ping.return_value = resp
        evidence = EvidenceStore(str(tmp_path / "ev.db"))
        result = neurologist_pulse(provider, evidence_store=evidence)
        assert "evidence_store" in result.checks
        assert result.checks["evidence_store"].ok is True

    def test_gpu_lock_free(self, tmp_path):
        provider = MagicMock()
        resp = MagicMock()
        resp.ok = True
        provider.ping.return_value = resp
        lock_path = str(tmp_path / "gpu.lock")
        result = neurologist_pulse(provider, gpu_lock_path=lock_path)
        assert "gpu_lock" in result.checks
        assert result.checks["gpu_lock"].ok is True
        assert "free" in result.checks["gpu_lock"].detail.lower()

    def test_gpu_lock_stale(self, tmp_path):
        provider = MagicMock()
        resp = MagicMock()
        resp.ok = True
        provider.ping.return_value = resp
        lock_path = tmp_path / "gpu.lock"
        lock_path.write_text("999999")  # Dead PID
        result = neurologist_pulse(provider, gpu_lock_path=str(lock_path))
        assert "gpu_lock" in result.checks
        assert result.checks["gpu_lock"].ok is False
        assert "stale" in result.checks["gpu_lock"].detail.lower()

    def test_summary_all_healthy(self):
        provider = MagicMock()
        resp = MagicMock()
        resp.ok = True
        provider.ping.return_value = resp
        result = neurologist_pulse(provider)
        assert "healthy" in result.summary.lower()


# ── neurologist_challenge ────────────────────────────────────────────


class TestNeurologistChallenge:
    def test_parses_challenges(self):
        provider = MagicMock()
        resp = MagicMock()
        resp.ok = True
        resp.content = json.dumps([
            {"claim": "Auth is safe", "challenge": "No MFA", "severity": "critical"},
        ])
        provider.query.return_value = resp
        result = neurologist_challenge("auth security", provider)
        assert isinstance(result, ChallengeResult)
        assert len(result.challenges) == 1
        assert result.challenges[0].severity == "critical"

    def test_empty_response(self):
        provider = MagicMock()
        resp = MagicMock()
        resp.ok = False
        resp.content = ""
        provider.query.return_value = resp
        result = neurologist_challenge("topic", provider)
        assert len(result.challenges) == 0

    def test_provider_error(self):
        provider = MagicMock()
        provider.query.side_effect = RuntimeError("LLM down")
        result = neurologist_challenge("topic", provider)
        assert len(result.challenges) == 0
        assert result.raw_response == ""

    def test_with_evidence_context(self, tmp_path):
        provider = MagicMock()
        resp = MagicMock()
        resp.ok = True
        resp.content = json.dumps([
            {"claim": "X", "challenge": "Y", "severity": "informational"},
        ])
        provider.query.return_value = resp
        evidence = EvidenceStore(str(tmp_path / "ev.db"))
        result = neurologist_challenge("topic", provider, evidence_store=evidence)
        assert isinstance(result, ChallengeResult)


# ── _parse_challenges ────────────────────────────────────────────────


class TestParseChallenges:
    def test_valid_json_array(self):
        raw = json.dumps([
            {"claim": "A", "challenge": "B", "severity": "critical"},
            {"claim": "C", "challenge": "D", "severity": "informational"},
        ])
        result = _parse_challenges(raw)
        assert len(result) == 2
        assert result[0].claim == "A"

    def test_empty_string(self):
        assert _parse_challenges("") == []

    def test_invalid_json(self):
        result = _parse_challenges("not json at all")
        assert len(result) == 1
        assert result[0].severity == "informational"

    def test_json_with_surrounding_text(self):
        raw = 'Here are the challenges: [{"claim": "X", "challenge": "Y", "severity": "critical"}] end'
        result = _parse_challenges(raw)
        assert len(result) == 1
        assert result[0].claim == "X"

    def test_single_object_wrapped_in_array(self):
        raw = json.dumps({"claim": "X", "challenge": "Y", "severity": "critical"})
        result = _parse_challenges(raw)
        assert len(result) == 1


# ── introspect ───────────────────────────────────────────────────────


class TestIntrospect:
    def test_successful_introspection(self):
        provider = MagicMock()
        resp = MagicMock()
        resp.ok = True
        resp.content = "I can do pattern matching."
        resp.model = "qwen3:4b"
        provider.query.return_value = resp
        results = introspect({"neurologist": provider})
        assert "neurologist" in results
        assert results["neurologist"].ok is True
        assert results["neurologist"].model == "qwen3:4b"

    def test_failed_introspection(self):
        provider = MagicMock()
        resp = MagicMock()
        resp.ok = False
        resp.content = "Error"
        resp.model = "qwen3:4b"
        provider.query.return_value = resp
        results = introspect({"neurologist": provider})
        assert results["neurologist"].ok is False

    def test_unreachable_provider(self):
        provider = MagicMock()
        provider.query.side_effect = ConnectionError("refused")
        results = introspect({"neurologist": provider})
        assert results["neurologist"].ok is False
        assert results["neurologist"].model == "unknown"

    def test_multiple_providers(self):
        providers = {}
        for name in ("cardiologist", "neurologist"):
            p = MagicMock()
            resp = MagicMock()
            resp.ok = True
            resp.content = f"I am {name}"
            resp.model = name
            p.query.return_value = resp
            providers[name] = p
        results = introspect(providers)
        assert len(results) == 2
        assert all(r.ok for r in results.values())


# ── neurologist_challenge with file_paths ───────────────────────────


class TestNeurologistChallengeWithFiles:
    """neurologist_challenge with file_paths parameter."""

    def test_file_content_included_in_prompt(self, tmp_path):
        """When file_paths provided, file contents appear in the prompt."""
        test_file = tmp_path / "example.py"
        test_file.write_text("def foo():\n    return 42\n")

        mock_neuro = MagicMock()
        mock_resp = MagicMock()
        mock_resp.ok = True
        mock_resp.content = '[]'
        mock_neuro.query.return_value = mock_resp

        neurologist_challenge("test topic", mock_neuro, file_paths=[str(test_file)])

        call_kwargs = mock_neuro.query.call_args
        prompt = call_kwargs.kwargs.get("prompt", call_kwargs[1].get("prompt", ""))
        assert "def foo():" in prompt
        assert "example.py" in prompt

    def test_missing_file_skipped_gracefully(self):
        """Non-existent file_paths don't crash."""
        mock_neuro = MagicMock()
        mock_resp = MagicMock()
        mock_resp.ok = True
        mock_resp.content = '[]'
        mock_neuro.query.return_value = mock_resp

        result = neurologist_challenge(
            "test topic", mock_neuro, file_paths=["/nonexistent/file.py"]
        )
        assert result.topic == "test topic"

    def test_file_paths_none_is_backward_compatible(self):
        """Not passing file_paths works exactly as before."""
        mock_neuro = MagicMock()
        mock_resp = MagicMock()
        mock_resp.ok = True
        mock_resp.content = '[]'
        mock_neuro.query.return_value = mock_resp

        result = neurologist_challenge("test topic", mock_neuro)
        assert result.topic == "test topic"
