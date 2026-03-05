"""Tests for direct query commands and dissent testing protocol."""
from __future__ import annotations

import json
from unittest.mock import MagicMock

import pytest

from three_surgeons.core.direct import (
    DissentResult,
    ask_local,
    ask_remote,
    resolve_disagreement,
    _parse_dissent,
)
from three_surgeons.core.direct import test_dissent as run_test_dissent


# ── DissentResult dataclass ──────────────────────────────────────────


class TestDissentResult:
    def test_fields(self):
        dr = DissentResult(
            topic="auth",
            steelmanned_argument="Strong case for X",
            counter_evidence=["evidence1", "evidence2"],
            verdict="dissent_valid",
            confidence=0.8,
            raw_response="raw",
        )
        assert dr.topic == "auth"
        assert dr.verdict == "dissent_valid"
        assert dr.confidence == 0.8
        assert len(dr.counter_evidence) == 2


# ── ask_local ────────────────────────────────────────────────────────


class TestAskLocal:
    def test_basic_query(self):
        provider = MagicMock()
        resp = MagicMock()
        resp.ok = True
        resp.content = "answer"
        provider.query.return_value = resp
        result = ask_local("What is X?", provider)
        assert result == resp
        provider.query.assert_called_once()

    def test_custom_system_prompt(self):
        provider = MagicMock()
        resp = MagicMock()
        provider.query.return_value = resp
        ask_local("prompt", provider, system_prompt="Custom system")
        args = provider.query.call_args
        assert args.kwargs["system"] == "Custom system"

    def test_default_system_prompt(self):
        provider = MagicMock()
        resp = MagicMock()
        provider.query.return_value = resp
        ask_local("prompt", provider)
        args = provider.query.call_args
        assert "local" in args.kwargs["system"].lower()


# ── ask_remote ───────────────────────────────────────────────────────


class TestAskRemote:
    def test_basic_query(self):
        provider = MagicMock()
        resp = MagicMock()
        resp.ok = True
        provider.query.return_value = resp
        result = ask_remote("What is X?", provider)
        assert result == resp

    def test_custom_system_prompt(self):
        provider = MagicMock()
        resp = MagicMock()
        provider.query.return_value = resp
        ask_remote("prompt", provider, system_prompt="Custom")
        args = provider.query.call_args
        assert args.kwargs["system"] == "Custom"


# ── test_dissent ─────────────────────────────────────────────────────


class TestTestDissent:
    def test_valid_dissent(self):
        provider = MagicMock()
        resp = MagicMock()
        resp.ok = True
        resp.content = json.dumps({
            "steelmanned_argument": "Strong case",
            "counter_evidence": ["point1"],
            "verdict": "dissent_valid",
            "confidence": 0.85,
        })
        provider.query.return_value = resp
        result = run_test_dissent("topic", "disagreement", provider)
        assert isinstance(result, DissentResult)
        assert result.verdict == "dissent_valid"
        assert result.confidence == 0.85

    def test_with_original_claim(self):
        provider = MagicMock()
        resp = MagicMock()
        resp.ok = True
        resp.content = json.dumps({
            "steelmanned_argument": "X",
            "counter_evidence": [],
            "verdict": "dissent_unfounded",
            "confidence": 0.3,
        })
        provider.query.return_value = resp
        result = run_test_dissent("topic", "view", provider, original_claim="original")
        assert result.verdict == "dissent_unfounded"

    def test_provider_error(self):
        provider = MagicMock()
        provider.query.side_effect = RuntimeError("down")
        result = run_test_dissent("topic", "view", provider)
        assert result.verdict == "dissent_partially_valid"
        assert result.confidence == 0.5

    def test_empty_response(self):
        provider = MagicMock()
        resp = MagicMock()
        resp.ok = False
        resp.content = ""
        provider.query.return_value = resp
        result = run_test_dissent("topic", "view", provider)
        assert result.steelmanned_argument == ""


# ── _parse_dissent ───────────────────────────────────────────────────


class TestParseDissent:
    def test_valid_json(self):
        raw = json.dumps({
            "steelmanned_argument": "Arg",
            "counter_evidence": ["e1"],
            "verdict": "dissent_valid",
            "confidence": 0.9,
        })
        result = _parse_dissent("topic", raw)
        assert result.verdict == "dissent_valid"
        assert result.confidence == 0.9

    def test_empty_string(self):
        result = _parse_dissent("topic", "")
        assert result.verdict == "dissent_partially_valid"
        assert result.confidence == 0.5

    def test_invalid_json(self):
        result = _parse_dissent("topic", "not json")
        assert result.steelmanned_argument == "not json"[:500]

    def test_json_with_surrounding_text(self):
        raw = 'Analysis: {"steelmanned_argument": "X", "verdict": "dissent_valid", "confidence": 0.7} end'
        result = _parse_dissent("topic", raw)
        assert result.verdict == "dissent_valid"


# ── resolve_disagreement ─────────────────────────────────────────────


class TestResolveDisagreement:
    def test_unanimous_tests_counter(self):
        provider = MagicMock()
        resp = MagicMock()
        resp.ok = True
        resp.content = json.dumps({
            "steelmanned_argument": "Maybe wrong",
            "counter_evidence": [],
            "verdict": "dissent_unfounded",
            "confidence": 0.3,
        })
        provider.query.return_value = resp
        result = resolve_disagreement(
            "topic",
            {"cardio": "agree", "neuro": "agree"},
            provider,
        )
        assert isinstance(result, DissentResult)

    def test_minority_steelmanned(self):
        provider = MagicMock()
        resp = MagicMock()
        resp.ok = True
        resp.content = json.dumps({
            "steelmanned_argument": "Minority has a point",
            "counter_evidence": ["evidence"],
            "verdict": "dissent_partially_valid",
            "confidence": 0.6,
        })
        provider.query.return_value = resp
        result = resolve_disagreement(
            "topic",
            {"cardio": "keep", "neuro": "keep", "atlas": "revert"},
            provider,
        )
        assert isinstance(result, DissentResult)

    def test_two_opinions(self):
        provider = MagicMock()
        resp = MagicMock()
        resp.ok = True
        resp.content = json.dumps({
            "steelmanned_argument": "X",
            "counter_evidence": [],
            "verdict": "dissent_valid",
            "confidence": 0.8,
        })
        provider.query.return_value = resp
        result = resolve_disagreement(
            "topic",
            {"cardio": "yes", "neuro": "no"},
            provider,
        )
        assert result.verdict == "dissent_valid"
