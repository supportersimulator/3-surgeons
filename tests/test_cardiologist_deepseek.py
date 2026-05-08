"""Tests for the DeepSeek-as-Cardiologist provider option.

The Cardiologist historically runs on OpenAI gpt-4.1-mini. These tests
cover the added ``provider`` switch (openai | deepseek):

* config preset fidelity for both providers,
* the ``--cardio-provider`` CLI flag mutating Config,
* the missing-API-key error path for DeepSeek,
* routing through ``LLMProvider._single_query`` against the correct
  endpoint (DeepSeek vs OpenAI) with all HTTP traffic mocked,
* ``cap_status`` / ``cmd_status`` reporting the active provider,
* default provider remains openai (backward-compat guard).

All network calls are mocked via ``unittest.mock`` so the suite runs
offline and does not require ``Context_DNA_OPENAI`` or
``Context_DNA_Deepseek`` to be set.
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from click.testing import CliRunner

# Ensure the package is importable when tests run from the repo root.
_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from three_surgeons.cli.main import cli  # noqa: E402
from three_surgeons.core.config import (  # noqa: E402
    CARDIOLOGIST_PROVIDER_PRESETS,
    Config,
    MissingProviderKeyError,
    OPENAI_TO_DEEPSEEK_MODEL,
    SurgeonConfig,
    cardiologist_provider_preset,
    make_cardiologist_config,
)
from three_surgeons.core.models import LLMProvider, LLMResponse  # noqa: E402


# ── Preset fidelity ───────────────────────────────────────────────────


class TestProviderPresets:
    def test_openai_preset_shape(self):
        preset = cardiologist_provider_preset("openai")
        assert preset["provider"] == "openai"
        assert preset["endpoint"] == "https://api.openai.com/v1"
        assert preset["model"] == "gpt-4.1-mini"
        assert preset["api_key_env"] == "Context_DNA_OPENAI"

    def test_deepseek_preset_shape(self):
        preset = cardiologist_provider_preset("deepseek")
        assert preset["provider"] == "deepseek"
        assert preset["endpoint"] == "https://api.deepseek.com/v1"
        assert preset["model"] == "deepseek-chat"
        assert preset["api_key_env"] == "Context_DNA_Deepseek"

    def test_unknown_provider_raises(self):
        # SS2 2026-05-08 — was "anthropic", which is now a real preset.
        # Use a clearly invalid name to keep the contract test meaningful.
        with pytest.raises(ValueError):
            cardiologist_provider_preset("not-a-real-provider")

    def test_presets_dict_exposes_both(self):
        # SS2 2026-05-08 — anthropic added as third option for cross-provider
        # diversity when openai billing is down and neuro is on deepseek.
        assert set(CARDIOLOGIST_PROVIDER_PRESETS) >= {"openai", "deepseek", "anthropic"}

    def test_openai_to_deepseek_mapping_covers_common_models(self):
        assert OPENAI_TO_DEEPSEEK_MODEL["gpt-4.1-mini"] == "deepseek-chat"
        assert OPENAI_TO_DEEPSEEK_MODEL["gpt-4o-mini"] == "deepseek-chat"
        assert OPENAI_TO_DEEPSEEK_MODEL["o1-mini"] == "deepseek-reasoner"


class TestMakeCardiologistConfig:
    def test_default_is_openai(self):
        cfg = make_cardiologist_config()
        assert cfg.provider == "openai"
        assert cfg.endpoint == "https://api.openai.com/v1"
        assert cfg.model == "gpt-4.1-mini"
        assert cfg.api_key_env == "Context_DNA_OPENAI"

    def test_deepseek_preset(self):
        cfg = make_cardiologist_config(provider="deepseek")
        assert cfg.provider == "deepseek"
        assert cfg.endpoint == "https://api.deepseek.com/v1"
        assert cfg.model == "deepseek-chat"
        assert cfg.api_key_env == "Context_DNA_Deepseek"

    def test_deepseek_translates_openai_model_override(self):
        cfg = make_cardiologist_config(provider="deepseek", model="gpt-4o-mini")
        assert cfg.model == "deepseek-chat"

    def test_deepseek_passthrough_for_native_model(self):
        cfg = make_cardiologist_config(provider="deepseek", model="deepseek-reasoner")
        assert cfg.model == "deepseek-reasoner"


# ── Config.apply_cardiologist_provider ────────────────────────────────


class TestApplyCardiologistProvider:
    def test_default_config_uses_openai(self):
        cfg = Config()
        assert cfg.cardiologist.provider == "openai"
        assert cfg.cardiologist.endpoint == "https://api.openai.com/v1"

    def test_apply_openai_is_noop_on_defaults(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("Context_DNA_OPENAI", "sk-openai-test-key-longenough")
        cfg = Config()
        cfg.apply_cardiologist_provider("openai")
        assert cfg.cardiologist.provider == "openai"
        assert cfg.cardiologist.model == "gpt-4.1-mini"

    def test_apply_deepseek_swaps_endpoint_and_model(
        self, monkeypatch: pytest.MonkeyPatch
    ):
        monkeypatch.setenv("Context_DNA_Deepseek", "sk-deepseek-test-key-longenough")
        cfg = Config()
        cfg.apply_cardiologist_provider("deepseek")
        assert cfg.cardiologist.provider == "deepseek"
        assert cfg.cardiologist.endpoint == "https://api.deepseek.com/v1"
        assert cfg.cardiologist.model == "deepseek-chat"
        assert cfg.cardiologist.api_key_env == "Context_DNA_Deepseek"

    def test_apply_deepseek_missing_key_raises(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.delenv("Context_DNA_Deepseek", raising=False)
        monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
        cfg = Config()
        with pytest.raises(MissingProviderKeyError) as excinfo:
            cfg.apply_cardiologist_provider("deepseek")
        message = str(excinfo.value)
        assert "deepseek" in message
        # Message must mention both accepted env var names for operability.
        assert "Context_DNA_Deepseek" in message
        assert "DEEPSEEK_API_KEY" in message

    def test_apply_deepseek_accepts_deepseek_api_key_fallback(
        self, monkeypatch: pytest.MonkeyPatch
    ):
        monkeypatch.delenv("Context_DNA_Deepseek", raising=False)
        monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-spec-deepseek-api-key-fallback")
        cfg = Config()
        cfg.apply_cardiologist_provider("deepseek")
        assert cfg.cardiologist.get_api_key() == "sk-spec-deepseek-api-key-fallback"

    def test_apply_preserves_role_and_fallbacks(
        self, monkeypatch: pytest.MonkeyPatch
    ):
        monkeypatch.setenv("Context_DNA_Deepseek", "sk-deepseek-test-key-longenough")
        cfg = Config()
        cfg.cardiologist.role = "Custom role"
        cfg.cardiologist.fallbacks = [{"provider": "openai", "model": "gpt-4.1-mini"}]
        cfg.apply_cardiologist_provider("deepseek")
        assert cfg.cardiologist.role == "Custom role"
        assert cfg.cardiologist.fallbacks == [
            {"provider": "openai", "model": "gpt-4.1-mini"}
        ]


# ── SurgeonConfig.get_api_key fallback semantics ──────────────────────


class TestGetApiKeyFallback:
    def test_deepseek_reads_primary_env(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("Context_DNA_Deepseek", "sk-primary-deepseek-key-value")
        monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-fallback-ignored-value")
        cfg = SurgeonConfig(provider="deepseek", api_key_env="Context_DNA_Deepseek")
        # Primary wins over the fallback.
        assert cfg.get_api_key() == "sk-primary-deepseek-key-value"

    def test_deepseek_fallback_when_primary_missing(
        self, monkeypatch: pytest.MonkeyPatch
    ):
        monkeypatch.delenv("Context_DNA_Deepseek", raising=False)
        monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-fallback-deepseek-key-value")
        cfg = SurgeonConfig(provider="deepseek", api_key_env="Context_DNA_Deepseek")
        assert cfg.get_api_key() == "sk-fallback-deepseek-key-value"

    def test_openai_does_not_use_deepseek_fallback(
        self, monkeypatch: pytest.MonkeyPatch
    ):
        monkeypatch.delenv("Context_DNA_OPENAI", raising=False)
        monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-not-used-here-value")
        cfg = SurgeonConfig(provider="openai", api_key_env="Context_DNA_OPENAI")
        assert cfg.get_api_key() is None


# ── HTTP routing (mocked) ─────────────────────────────────────────────


def _mock_chat_response(model: str) -> MagicMock:
    """Build a MagicMock that mimics an httpx.Response for /chat/completions."""
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


class TestLLMProviderRouting:
    def test_openai_cardiologist_hits_openai_endpoint(
        self, monkeypatch: pytest.MonkeyPatch
    ):
        monkeypatch.setenv("Context_DNA_OPENAI", "sk-openai-test-key-longenough")
        cfg = Config()  # default: cardiologist=openai
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
        assert captured["url"].startswith("https://api.openai.com/v1")
        assert captured["url"].endswith("/chat/completions")
        assert captured["model"] == "gpt-4.1-mini"
        assert captured["auth"] == "Bearer sk-openai-test-key-longenough"

    def test_deepseek_cardiologist_hits_deepseek_endpoint(
        self, monkeypatch: pytest.MonkeyPatch
    ):
        monkeypatch.setenv("Context_DNA_Deepseek", "sk-deepseek-test-key-longenough")
        cfg = Config().apply_cardiologist_provider("deepseek")
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
        assert captured["url"].startswith("https://api.deepseek.com/v1")
        assert captured["url"].endswith("/chat/completions")
        assert captured["model"] == "deepseek-chat"
        assert captured["auth"] == "Bearer sk-deepseek-test-key-longenough"

    def test_deepseek_provider_missing_key_surfaces_clear_error(
        self, monkeypatch: pytest.MonkeyPatch
    ):
        monkeypatch.delenv("Context_DNA_Deepseek", raising=False)
        monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
        cfg = Config()
        with pytest.raises(MissingProviderKeyError) as excinfo:
            cfg.apply_cardiologist_provider("deepseek")
        assert "DEEPSEEK_API_KEY" in str(excinfo.value)


# ── cap_status / cmd_status reporting ─────────────────────────────────


class TestCapStatusProviderReporting:
    def _ctx(self, config: Config, healthy: list):
        from three_surgeons.core.requirements import RuntimeContext

        state = MagicMock()
        state.get = MagicMock(return_value=None)
        state.list_range = MagicMock(return_value=[])
        return RuntimeContext(
            healthy_llms=healthy,
            state=state,
            evidence=MagicMock(),
            git_available=False,
            git_root=None,
            config=config,
        )

    def test_cmd_status_reports_openai_by_default(self):
        from three_surgeons.core.status_commands import cmd_status

        cfg = Config()
        healthy = [MagicMock(model="gpt-4.1-mini"), MagicMock(model="qwen3:4b")]
        ctx = self._ctx(cfg, healthy)

        result = cmd_status(ctx)
        cardio = result.data["surgeons"]["cardiologist"]
        assert cardio["provider"] == "openai"
        assert cardio["model"] == "gpt-4.1-mini"
        assert cardio["healthy"] is True

    def test_cmd_status_reports_deepseek_after_override(
        self, monkeypatch: pytest.MonkeyPatch
    ):
        from three_surgeons.core.status_commands import cmd_status

        monkeypatch.setenv("Context_DNA_Deepseek", "sk-deepseek-test-key-longenough")
        cfg = Config().apply_cardiologist_provider("deepseek")
        healthy = [MagicMock(model="deepseek-chat"), MagicMock(model="qwen3:4b")]
        ctx = self._ctx(cfg, healthy)

        result = cmd_status(ctx)
        cardio = result.data["surgeons"]["cardiologist"]
        assert cardio["provider"] == "deepseek"
        assert cardio["model"] == "deepseek-chat"
        assert cardio["healthy"] is True


# ── CLI flag integration ──────────────────────────────────────────────


class TestCardioProviderCliFlag:
    def test_flag_overrides_config_cardiologist(
        self, monkeypatch: pytest.MonkeyPatch
    ):
        """``3s --cardio-provider=deepseek probe --dry-run`` flips the config."""
        monkeypatch.setenv("Context_DNA_Deepseek", "sk-deepseek-test-key-longenough")

        # Spy on Config.apply_cardiologist_provider to confirm it was called.
        from three_surgeons.core import config as config_module

        real_apply = config_module.Config.apply_cardiologist_provider
        calls: list = []

        def spy(self, provider, require_key=True):
            calls.append((provider, require_key))
            return real_apply(self, provider, require_key=require_key)

        monkeypatch.setattr(config_module.Config, "apply_cardiologist_provider", spy)

        runner = CliRunner()
        result = runner.invoke(
            cli, ["--cardio-provider", "deepseek", "probe", "--dry-run"]
        )
        assert result.exit_code == 0, result.output
        assert calls, "Config.apply_cardiologist_provider was not called"
        assert calls[0][0].lower() == "deepseek"
        # CLI layer uses require_key=False so --help / probe still work
        # without the key (call-site runtime will surface missing keys).
        assert calls[0][1] is False

    def test_flag_rejects_unknown_provider(self):
        runner = CliRunner()
        result = runner.invoke(cli, ["--cardio-provider", "bogus", "probe", "--dry-run"])
        # click.Choice rejects before our code runs.
        assert result.exit_code != 0
        assert "bogus" in result.output.lower() or "invalid" in result.output.lower()

    def test_flag_default_absent_keeps_openai(self):
        runner = CliRunner()
        result = runner.invoke(cli, ["probe", "--dry-run"])
        assert result.exit_code == 0, result.output
        # Default must remain OpenAI when --cardio-provider is not passed.
        cfg = Config.discover()
        assert cfg.cardiologist.provider == "openai"


# ── Backward-compatibility invariant ──────────────────────────────────


class TestBackwardCompat:
    def test_default_cardiologist_remains_openai(self):
        cfg = Config()
        assert cfg.cardiologist.provider == "openai"
        assert cfg.cardiologist.model == "gpt-4.1-mini"
        assert cfg.cardiologist.endpoint == "https://api.openai.com/v1"
        assert cfg.cardiologist.api_key_env == "Context_DNA_OPENAI"

    def test_llm_response_shape_unchanged(self):
        resp = LLMResponse(ok=True, content="x", model="gpt-4.1-mini")
        assert resp.ok is True
        assert resp.content == "x"
        assert resp.model == "gpt-4.1-mini"
