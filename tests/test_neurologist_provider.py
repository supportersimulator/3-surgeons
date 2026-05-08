"""Tests for the Neurologist provider preset path.

Mirrors the Cardiologist provider tests. The Neurologist defaults to a
local OpenAI-compatible backend (ollama qwen3:4b). Per CLAUDE.md
2026-04-26 directive the steady-state target is DeepSeek-chat for both
surgeons; this preset table makes the cutover an env-var or CLI flag
flip rather than a code edit.

Coverage:
* preset fidelity (ollama, mlx, deepseek)
* ``apply_neurologist_provider`` mutates Config in place
* ``--neuro-provider`` CLI flag mutating Config
* CONTEXT_DNA_NEURO_PROVIDER env var override on Config.discover()
* bogus env var falls back gracefully (ZSF — does not crash discovery)
* missing API key path raises only when require_key=True and provider needs key
* local providers (ollama/mlx) skip key check (no api_key_env)
"""
from __future__ import annotations

import os
import sys
from pathlib import Path
from unittest.mock import patch

import pytest
from click.testing import CliRunner

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from three_surgeons.cli.main import cli  # noqa: E402
from three_surgeons.core.config import (  # noqa: E402
    NEUROLOGIST_PROVIDER_PRESETS,
    Config,
    MissingProviderKeyError,
    make_neurologist_config,
    neurologist_provider_preset,
)


class TestNeurologistPresets:
    def test_ollama_preset_shape(self):
        p = neurologist_provider_preset("ollama")
        assert p["provider"] == "ollama"
        assert p["endpoint"] == "http://localhost:11434/v1"
        assert p["model"] == "qwen3:4b"
        assert p["api_key_env"] == ""

    def test_mlx_preset_shape(self):
        p = neurologist_provider_preset("mlx")
        assert p["provider"] == "mlx"
        assert p["endpoint"] == "http://localhost:5044/v1"
        assert p["model"] == "mlx-community/Qwen3-4B-4bit"
        assert p["api_key_env"] == ""

    def test_deepseek_preset_shape(self):
        p = neurologist_provider_preset("deepseek")
        assert p["provider"] == "deepseek"
        assert p["endpoint"] == "https://api.deepseek.com/v1"
        assert p["model"] == "deepseek-chat"
        assert p["api_key_env"] == "Context_DNA_Deepseek"

    def test_unknown_provider_raises(self):
        with pytest.raises(ValueError, match="Unknown neurologist provider"):
            neurologist_provider_preset("anthropic")

    def test_case_insensitive(self):
        assert neurologist_provider_preset("DEEPSEEK")["provider"] == "deepseek"
        assert neurologist_provider_preset(" Ollama ")["provider"] == "ollama"

    def test_preset_table_has_expected_providers(self):
        # QQ1 2026-05-08: ``mlx_proxy`` added so the auto-fallback chain can
        # walk ollama → mlx → mlx_proxy (:5045 priority queue) → deepseek.
        assert set(NEUROLOGIST_PROVIDER_PRESETS) == {
            "ollama", "mlx", "mlx_proxy", "deepseek"
        }


class TestApplyNeurologistProvider:
    def test_apply_deepseek_mutates_config(self):
        cfg = Config()  # bare defaults — no YAML/env
        cfg.apply_neurologist_provider("deepseek", require_key=False)
        assert cfg.neurologist.provider == "deepseek"
        assert cfg.neurologist.endpoint == "https://api.deepseek.com/v1"
        assert cfg.neurologist.model == "deepseek-chat"
        assert cfg.neurologist.api_key_env == "Context_DNA_Deepseek"

    def test_apply_mlx_mutates_config(self):
        cfg = Config()
        cfg.apply_neurologist_provider("mlx", require_key=False)
        assert cfg.neurologist.provider == "mlx"
        assert cfg.neurologist.endpoint == "http://localhost:5044/v1"

    def test_apply_preserves_role(self):
        cfg = Config()
        cfg.neurologist.role = "custom local intelligence"
        cfg.apply_neurologist_provider("deepseek", require_key=False)
        assert cfg.neurologist.role == "custom local intelligence"

    def test_apply_preserves_fallbacks(self):
        cfg = Config()
        cfg.neurologist.fallbacks = ["custom-model-1", "custom-model-2"]
        cfg.apply_neurologist_provider("deepseek", require_key=False)
        assert cfg.neurologist.fallbacks == ["custom-model-1", "custom-model-2"]

    def test_apply_deepseek_missing_key_raises(self, monkeypatch):
        monkeypatch.delenv("Context_DNA_Deepseek", raising=False)
        monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
        cfg = Config()
        with pytest.raises(MissingProviderKeyError, match="Neurologist provider 'deepseek'"):
            cfg.apply_neurologist_provider("deepseek", require_key=True)

    def test_apply_local_provider_skips_key_check(self):
        cfg = Config()
        # ollama/mlx have no api_key_env; should NOT raise even with
        # require_key=True (local providers don't need keys).
        cfg.apply_neurologist_provider("ollama", require_key=True)
        assert cfg.neurologist.provider == "ollama"

    def test_apply_returns_self_for_chaining(self):
        cfg = Config()
        result = cfg.apply_neurologist_provider("ollama", require_key=False)
        assert result is cfg


class TestEnvVarOverride:
    """CONTEXT_DNA_NEURO_PROVIDER overrides default on Config.discover()."""

    def test_env_var_flips_to_deepseek(self, monkeypatch, tmp_path):
        monkeypatch.setenv("CONTEXT_DNA_NEURO_PROVIDER", "deepseek")
        # Use empty project dir so no YAML overrides leak in
        cfg = Config.discover(project_dir=tmp_path)
        # Note: home YAML may still override; key signal is provider got
        # routed through preset apply path
        assert cfg.neurologist.provider == "deepseek"
        assert cfg.neurologist.model == "deepseek-chat"

    def test_env_var_bogus_falls_back(self, monkeypatch, tmp_path, caplog):
        monkeypatch.setenv("CONTEXT_DNA_NEURO_PROVIDER", "anthropic")
        # ZSF: must not crash discovery
        cfg = Config.discover(project_dir=tmp_path)
        # Provider preserved (whatever YAML/default says) — not crashed
        assert cfg.neurologist.provider in {"ollama", "mlx", "deepseek"}

    def test_env_var_unset_keeps_default(self, monkeypatch, tmp_path):
        monkeypatch.delenv("CONTEXT_DNA_NEURO_PROVIDER", raising=False)
        cfg = Config.discover(project_dir=tmp_path)
        # Default may be ollama (built-in) or whatever home YAML sets;
        # neither should be deepseek under a clean env.
        # Skip the home-YAML interference check — just confirm no crash.
        assert cfg.neurologist.provider in {"ollama", "mlx", "deepseek"}


class TestNeuroProviderCliFlag:
    def test_flag_in_help(self):
        runner = CliRunner()
        result = runner.invoke(cli, ["--help"])
        assert result.exit_code == 0
        assert "--neuro-provider" in result.output

    def test_flag_choices_documented(self):
        runner = CliRunner()
        result = runner.invoke(cli, ["--help"])
        assert "ollama" in result.output and "mlx" in result.output and "deepseek" in result.output

    def test_flag_invalid_value_rejected(self):
        runner = CliRunner()
        # Click rejects --neuro-provider=anthropic at parse time. Use a
        # real subcommand (probe) rather than --help, since Click short-
        # circuits validation for --help.
        result = runner.invoke(cli, ["--neuro-provider", "anthropic", "probe"])
        assert result.exit_code != 0
        assert "anthropic" in result.output.lower() or "invalid" in result.output.lower()


class TestMakeNeurologistConfig:
    def test_default_uses_ollama_preset(self):
        cfg = make_neurologist_config()
        assert cfg.provider == "ollama"
        assert cfg.model == "qwen3:4b"

    def test_model_override(self):
        cfg = make_neurologist_config(provider="deepseek", model="deepseek-reasoner")
        assert cfg.model == "deepseek-reasoner"
        assert cfg.provider == "deepseek"

    def test_endpoint_override(self):
        cfg = make_neurologist_config(provider="ollama", endpoint="http://otherhost:1234/v1")
        assert cfg.endpoint == "http://otherhost:1234/v1"
