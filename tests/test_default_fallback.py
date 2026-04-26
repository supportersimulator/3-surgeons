"""Tests for the default DeepSeek fallback shipped with Config.cardiologist.

Goal: out-of-the-box, a fresh ``Config()`` provides a DeepSeek fallback for the
cardiologist surgeon so an OpenAI 429 (billing/quota) auto-recovers without
operator YAML edits. Operators who explicitly set ``fallbacks`` retain full
control -- their list wins (no merge).
"""
from __future__ import annotations

import os
from pathlib import Path

import pytest
import yaml

from three_surgeons.core.config import (
    DEEPSEEK_DEFAULT_FALLBACK,
    Config,
    SurgeonConfig,
    _default_cardiologist,
)


class TestDefaultFallback:
    """Empty Config -> cardiologist gets a DeepSeek fallback chain."""

    def test_default_config_has_deepseek_fallback(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Construct ``Config()`` with no env, no YAML -> DeepSeek fallback shipped."""
        monkeypatch.delenv("LLM_PROVIDER", raising=False)
        cfg = Config()

        assert cfg.cardiologist.provider == "openai", "primary should remain OpenAI"
        assert cfg.cardiologist.fallbacks, "fallbacks list must not be empty"
        first = cfg.cardiologist.fallbacks[0]
        assert first["provider"] == "deepseek"
        assert first["endpoint"] == "https://api.deepseek.com/v1"
        assert first["model"] == "deepseek-chat"
        assert first["api_key_env"] == "Context_DNA_Deep_Seek"

    def test_default_fallback_resolves_to_surgeon_configs(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """``get_fallback_configs()`` materialises the default into SurgeonConfig."""
        monkeypatch.delenv("LLM_PROVIDER", raising=False)
        cfg = Config()
        chain = cfg.cardiologist.get_fallback_configs()

        assert len(chain) == 1
        deepseek = chain[0]
        assert isinstance(deepseek, SurgeonConfig)
        assert deepseek.provider == "deepseek"
        assert deepseek.model == "deepseek-chat"
        assert deepseek.api_key_env == "Context_DNA_Deep_Seek"

    def test_default_fallback_is_isolated(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Each Config() gets its own list -- mutation must not leak across instances."""
        monkeypatch.delenv("LLM_PROVIDER", raising=False)
        cfg_a = Config()
        cfg_b = Config()

        # Mutating one must not pollute the other or the module-level constant
        cfg_a.cardiologist.fallbacks.append({"provider": "stub"})

        assert len(cfg_b.cardiologist.fallbacks) == 1
        assert "stub" not in [fb.get("provider") for fb in cfg_b.cardiologist.fallbacks]
        assert "stub" not in [
            fb.get("provider") for fb in [DEEPSEEK_DEFAULT_FALLBACK]
        ]


class TestUserFallbacksWin:
    """Operator-supplied fallbacks override the default -- no merge."""

    def test_explicit_fallbacks_replace_default(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """YAML ``fallbacks: [...]`` on cardiologist wins -- no merge with default."""
        monkeypatch.delenv("LLM_PROVIDER", raising=False)
        config_data = {
            "surgeons": {
                "cardiologist": {
                    "provider": "openai",
                    "endpoint": "https://api.openai.com/v1",
                    "model": "gpt-4.1-mini",
                    "api_key_env": "Context_DNA_OPENAI",
                    "fallbacks": [
                        {
                            "provider": "anthropic",
                            "endpoint": "https://api.anthropic.com/v1",
                            "model": "claude-3-5-haiku-latest",
                            "api_key_env": "ANTHROPIC_API_KEY",
                        }
                    ],
                }
            }
        }
        path = tmp_path / "config.yaml"
        path.write_text(yaml.dump(config_data))

        cfg = Config.from_yaml(path)
        assert len(cfg.cardiologist.fallbacks) == 1
        assert cfg.cardiologist.fallbacks[0]["provider"] == "anthropic"
        # No DeepSeek leaked through
        providers = [fb["provider"] for fb in cfg.cardiologist.fallbacks]
        assert "deepseek" not in providers

    def test_explicit_empty_fallbacks_wins(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Operator can disable the default with ``fallbacks: []``."""
        monkeypatch.delenv("LLM_PROVIDER", raising=False)
        config_data = {
            "surgeons": {
                "cardiologist": {
                    "fallbacks": [],
                }
            }
        }
        path = tmp_path / "config.yaml"
        path.write_text(yaml.dump(config_data))

        cfg = Config.from_yaml(path)
        assert cfg.cardiologist.fallbacks == []


class TestEnvKeyResolution:
    """Both DeepSeek env aliases work; absence is graceful."""

    def test_canonical_env_resolves(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Canonical ``Context_DNA_Deep_Seek`` returns the key directly."""
        monkeypatch.delenv("LLM_PROVIDER", raising=False)
        monkeypatch.delenv("Context_DNA_Deepseek", raising=False)
        monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
        monkeypatch.setenv("Context_DNA_Deep_Seek", "sk-canonical-12345")

        cfg = Config()
        deepseek = cfg.cardiologist.get_fallback_configs()[0]
        assert deepseek.get_api_key() == "sk-canonical-12345"

    def test_alias_env_resolves(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Legacy ``Context_DNA_Deepseek`` alias still resolves."""
        monkeypatch.delenv("LLM_PROVIDER", raising=False)
        monkeypatch.delenv("Context_DNA_Deep_Seek", raising=False)
        monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
        monkeypatch.setenv("Context_DNA_Deepseek", "sk-alias-67890")

        cfg = Config()
        deepseek = cfg.cardiologist.get_fallback_configs()[0]
        assert deepseek.get_api_key() == "sk-alias-67890"

    def test_both_keys_absent_is_graceful(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """No DeepSeek env vars set -> ``get_api_key()`` returns None, no crash."""
        monkeypatch.delenv("LLM_PROVIDER", raising=False)
        monkeypatch.delenv("Context_DNA_Deep_Seek", raising=False)
        monkeypatch.delenv("Context_DNA_Deepseek", raising=False)
        monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)

        cfg = Config()
        deepseek = cfg.cardiologist.get_fallback_configs()[0]
        # Must not raise; just signals key missing.
        assert deepseek.get_api_key() is None


class TestPrimaryDeepSeekNoSelfFallback:
    """When LLM_PROVIDER=deepseek, the primary IS DeepSeek -- no self-fallback."""

    def test_deepseek_primary_has_no_fallback(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("LLM_PROVIDER", "deepseek")
        cfg = Config()
        assert cfg.cardiologist.provider == "deepseek"
        assert cfg.cardiologist.fallbacks == []


class TestFactoryDirect:
    """Sanity: ``_default_cardiologist()`` produces the expected shape."""

    def test_openai_branch_includes_deepseek_fallback(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("LLM_PROVIDER", raising=False)
        sc = _default_cardiologist()
        assert sc.provider == "openai"
        assert sc.fallbacks and sc.fallbacks[0]["provider"] == "deepseek"
