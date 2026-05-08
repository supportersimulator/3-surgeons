"""Tests for the Anthropic-as-Cardiologist provider option (SS2 2026-05-08).

Restores the 3-surgeon model-diversity invariant. RR5 found OpenAI cardio
billing is inactive (`billing_not_active`); the existing fallback was
DeepSeek, but neuro is also pinned to DeepSeek (CLAUDE.md 2026-04-26
cutover). Both surgeons on DeepSeek collapses cross-examination to
self-agreement. Adding Anthropic as a third provider restores genuine
cross-provider diversity (Anthropic Haiku 4.5 + DeepSeek-chat).

Coverage:
* preset shape correct (provider/endpoint/model/api_key_env),
* apply_cardiologist_provider mutates Config in place,
* missing API key raises MissingProviderKeyError mentioning both env vars,
* ANTHROPIC_API_KEY honored as a fallback (parity with DEEPSEEK_API_KEY),
* CLI flag accepts "anthropic" and rejects bogus values,
* mocked /v1/chat/completions hits api.anthropic.com with Bearer auth,
* default provider stays openai (backward-compat invariant).

All HTTP traffic is mocked. Tests run offline; they do NOT require
Context_DNA_Anthropic / ANTHROPIC_API_KEY to be set.
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from click.testing import CliRunner

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from three_surgeons.cli.main import cli  # noqa: E402
from three_surgeons.core.config import (  # noqa: E402
    CARDIOLOGIST_PROVIDER_PRESETS,
    Config,
    MissingProviderKeyError,
    SurgeonConfig,
    cardiologist_provider_preset,
    make_cardiologist_config,
)
from three_surgeons.core.models import LLMProvider  # noqa: E402


# ── Preset shape ──────────────────────────────────────────────────────


class TestAnthropicPresetShape:
    def test_anthropic_preset_in_dict(self):
        assert "anthropic" in CARDIOLOGIST_PROVIDER_PRESETS

    def test_anthropic_preset_fields(self):
        preset = cardiologist_provider_preset("anthropic")
        assert preset["provider"] == "anthropic"
        assert preset["endpoint"] == "https://api.anthropic.com/v1"
        assert preset["model"] == "claude-haiku-4-5-20251001"
        assert preset["api_key_env"] == "Context_DNA_Anthropic"

    def test_make_cardiologist_config_anthropic(self):
        cfg = make_cardiologist_config(provider="anthropic")
        assert cfg.provider == "anthropic"
        assert cfg.endpoint == "https://api.anthropic.com/v1"
        assert cfg.model == "claude-haiku-4-5-20251001"
        assert cfg.api_key_env == "Context_DNA_Anthropic"

    def test_make_cardiologist_config_anthropic_model_override(self):
        # User can override to Sonnet for higher-quality cross-exam.
        cfg = make_cardiologist_config(
            provider="anthropic", model="claude-sonnet-4-20250514"
        )
        assert cfg.provider == "anthropic"
        assert cfg.model == "claude-sonnet-4-20250514"


# ── apply_cardiologist_provider("anthropic") ──────────────────────────


class TestApplyAnthropicCardiologist:
    def test_apply_anthropic_swaps_endpoint_and_model(
        self, monkeypatch: pytest.MonkeyPatch
    ):
        monkeypatch.setenv("Context_DNA_Anthropic", "sk-ant-test-key-longenough")
        cfg = Config()
        cfg.apply_cardiologist_provider("anthropic")
        assert cfg.cardiologist.provider == "anthropic"
        assert cfg.cardiologist.endpoint == "https://api.anthropic.com/v1"
        assert cfg.cardiologist.model == "claude-haiku-4-5-20251001"
        assert cfg.cardiologist.api_key_env == "Context_DNA_Anthropic"

    def test_apply_anthropic_missing_key_raises(
        self, monkeypatch: pytest.MonkeyPatch
    ):
        monkeypatch.delenv("Context_DNA_Anthropic", raising=False)
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        cfg = Config()
        with pytest.raises(MissingProviderKeyError) as excinfo:
            cfg.apply_cardiologist_provider("anthropic")
        message = str(excinfo.value)
        assert "anthropic" in message.lower()
        # Both accepted env-var names must be advertised so users have
        # a clear remediation path on first failure.
        assert "Context_DNA_Anthropic" in message
        assert "ANTHROPIC_API_KEY" in message

    def test_anthropic_api_key_fallback_env(
        self, monkeypatch: pytest.MonkeyPatch
    ):
        monkeypatch.delenv("Context_DNA_Anthropic", raising=False)
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-fallback-key-longenough")
        cfg = Config()
        cfg.apply_cardiologist_provider("anthropic")
        # The configured api_key_env is Context_DNA_Anthropic, but the
        # provider-specific fallback chain in get_api_key() reads
        # ANTHROPIC_API_KEY when Context_DNA_Anthropic is unset.
        assert cfg.cardiologist.get_api_key() == "sk-ant-fallback-key-longenough"

    def test_anthropic_does_not_use_deepseek_fallback(
        self, monkeypatch: pytest.MonkeyPatch
    ):
        # Cross-provider env-var pollution must not leak.
        monkeypatch.delenv("Context_DNA_Anthropic", raising=False)
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-not-relevant-here-key")
        cfg = SurgeonConfig(provider="anthropic", api_key_env="Context_DNA_Anthropic")
        assert cfg.get_api_key() is None


# ── HTTP routing (mocked) ─────────────────────────────────────────────


def _mock_chat_response(model: str) -> MagicMock:
    resp = MagicMock()
    resp.status_code = 200
    resp.raise_for_status = MagicMock()
    resp.json = MagicMock(
        return_value={
            "choices": [{"message": {"content": "operational"}}],
            "usage": {"prompt_tokens": 5, "completion_tokens": 1},
            "model": model,
        }
    )
    return resp


class TestAnthropicCardiologistHttpRouting:
    def test_anthropic_cardiologist_hits_anthropic_endpoint(
        self, monkeypatch: pytest.MonkeyPatch
    ):
        monkeypatch.setenv("Context_DNA_Anthropic", "sk-ant-test-key-longenough")
        cfg = Config().apply_cardiologist_provider("anthropic")
        provider = LLMProvider(cfg.cardiologist)

        captured: dict = {}

        class FakeClient:
            def __init__(self, *a, **kw):
                pass

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

            def post(self, url, json=None, headers=None):
                captured["url"] = url
                captured["model"] = json["model"]
                captured["auth"] = headers.get("Authorization")
                return _mock_chat_response(json["model"])

        with patch("three_surgeons.core.models.httpx.Client", FakeClient):
            resp = provider.query(system="s", prompt="p", max_tokens=16)

        assert resp.ok is True
        assert captured["url"].startswith("https://api.anthropic.com/v1")
        assert captured["url"].endswith("/chat/completions")
        assert captured["model"] == "claude-haiku-4-5-20251001"
        assert captured["auth"] == "Bearer sk-ant-test-key-longenough"


# ── CLI flag integration ──────────────────────────────────────────────


class TestAnthropicCliFlag:
    def test_flag_accepts_anthropic(self, monkeypatch: pytest.MonkeyPatch):
        """``3s --cardio-provider=anthropic probe --dry-run`` flips the config."""
        monkeypatch.setenv("Context_DNA_Anthropic", "sk-ant-test-key-longenough")
        runner = CliRunner()
        result = runner.invoke(
            cli, ["--cardio-provider", "anthropic", "probe", "--dry-run"]
        )
        assert result.exit_code == 0, result.output

    def test_flag_rejects_bogus_provider(self):
        runner = CliRunner()
        result = runner.invoke(
            cli, ["--cardio-provider", "totally-bogus", "probe", "--dry-run"]
        )
        assert result.exit_code != 0
        assert (
            "totally-bogus" in result.output.lower()
            or "invalid" in result.output.lower()
        )


# ── Backward-compat invariant ─────────────────────────────────────────


class TestBackwardCompat:
    def test_default_cardiologist_remains_openai(self):
        # Adding Anthropic as a preset must not change the default.
        cfg = Config()
        assert cfg.cardiologist.provider == "openai"
        assert cfg.cardiologist.model == "gpt-4.1-mini"
