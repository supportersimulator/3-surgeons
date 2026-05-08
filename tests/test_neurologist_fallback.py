"""QQ1 2026-05-08 — Tests for the neurologist auto-fallback chain.

Bug fixed (PP1 commit 83b21e29b): default ``3s consensus`` returned
``Neurologist: unavailable`` on nodes where ollama was down (e.g. mac3).
Per CLAUDE.md 2026-04-26 directive DeepSeek-chat is the steady-state
target for both surgeons, but the CLI default had not been flipped.

This module pins the auto-fallback contract:

    1. Healthy node (ollama up) → ollama wins, default behavior unchanged.
    2. ollama down + mlx up → mlx wins; mlx counter increments.
    3. ollama+mlx down + mlx_proxy (5045) up → proxy wins.
    4. all-local down + DeepSeek key present → deepseek wins.
    5. all-local down + no DeepSeek key → no provider reachable;
       neurologist preserved at default (fail-safe).
    6. CONTEXT_DNA_NEURO_PROVIDER set → no fallback runs (explicit wins).
    7. CONTEXT_DNA_NEURO_FALLBACK_DISABLE=1 → no fallback runs.

The probe is monkey-patched at the ``_probe_provider_reachable`` seam so
tests are network-free and deterministic.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from three_surgeons.core import config as config_mod  # noqa: E402
from three_surgeons.core.config import (  # noqa: E402
    NEUROLOGIST_FALLBACK_CHAIN,
    Config,
    get_neuro_fallback_counters,
    reset_neuro_fallback_counters,
)


# --- probe-stub helpers ----------------------------------------------------


def _make_probe_stub(reachable: dict[str, bool]):
    """Return a fake _probe_provider_reachable that uses ``reachable``."""

    def _stub(provider_key: str, timeout_s: float = 2.0) -> bool:
        return reachable.get(provider_key, False)

    return _stub


@pytest.fixture(autouse=True)
def _isolate_counters():
    """Each test starts with zeroed counters so assertions are local."""
    reset_neuro_fallback_counters()
    yield
    reset_neuro_fallback_counters()


@pytest.fixture
def _clean_env(monkeypatch):
    """Strip env vars that bias the resolver path."""
    monkeypatch.delenv("CONTEXT_DNA_NEURO_PROVIDER", raising=False)
    monkeypatch.delenv("CONTEXT_DNA_NEURO_FALLBACK_DISABLE", raising=False)
    monkeypatch.delenv("Context_DNA_Deepseek", raising=False)
    monkeypatch.delenv("Context_DNA_Deep_Seek", raising=False)
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    yield


# --- 1. Healthy node ------------------------------------------------------


class TestHealthyNodePreservesDefault:
    def test_ollama_up_wins_first(self, _clean_env, tmp_path):
        # Everything reachable — ollama wins because it's first in chain.
        probe = _make_probe_stub({k: True for k in NEUROLOGIST_FALLBACK_CHAIN})
        with patch.object(config_mod, "_probe_provider_reachable", probe):
            cfg = Config.discover(project_dir=tmp_path)
        assert cfg.neurologist.provider == "ollama"
        assert cfg.neurologist.endpoint == "http://localhost:11434/v1"
        counters = get_neuro_fallback_counters()
        assert counters["ollama"] == 1
        # No other branch fired.
        for k in ("mlx", "mlx_proxy", "deepseek", "no_provider_reachable"):
            assert counters[k] == 0


# --- 2. mac3 case (ollama down, mlx up) -----------------------------------


class TestOllamaDownMlxUp:
    def test_falls_back_to_mlx(self, _clean_env, tmp_path):
        probe = _make_probe_stub({
            "ollama": False,
            "mlx": True,
            "mlx_proxy": True,
            "deepseek": True,
        })
        with patch.object(config_mod, "_probe_provider_reachable", probe):
            cfg = Config.discover(project_dir=tmp_path)
        assert cfg.neurologist.provider == "mlx"
        assert cfg.neurologist.endpoint == "http://localhost:5044/v1"
        counters = get_neuro_fallback_counters()
        assert counters["mlx"] == 1
        assert counters["ollama"] == 0


# --- 3. ollama + mlx down, proxy up ---------------------------------------


class TestProxyFallback:
    def test_falls_back_to_mlx_proxy(self, _clean_env, tmp_path):
        probe = _make_probe_stub({
            "ollama": False,
            "mlx": False,
            "mlx_proxy": True,
            "deepseek": True,
        })
        with patch.object(config_mod, "_probe_provider_reachable", probe):
            cfg = Config.discover(project_dir=tmp_path)
        assert cfg.neurologist.provider == "mlx"  # mlx_proxy preset uses provider=mlx
        assert cfg.neurologist.endpoint == "http://localhost:5045/v1"
        counters = get_neuro_fallback_counters()
        assert counters["mlx_proxy"] == 1


# --- 4. all-local down, deepseek key present ------------------------------


class TestDeepSeekFallback:
    def test_deepseek_wins_when_only_cloud_reachable(self, _clean_env, tmp_path):
        probe = _make_probe_stub({
            "ollama": False,
            "mlx": False,
            "mlx_proxy": False,
            "deepseek": True,
        })
        with patch.object(config_mod, "_probe_provider_reachable", probe):
            cfg = Config.discover(project_dir=tmp_path)
        assert cfg.neurologist.provider == "deepseek"
        assert cfg.neurologist.endpoint == "https://api.deepseek.com/v1"
        assert cfg.neurologist.model == "deepseek-chat"
        counters = get_neuro_fallback_counters()
        assert counters["deepseek"] == 1


# --- 5. all-local down, no DeepSeek key (fail-safe) -----------------------


class TestNoProviderReachable:
    def test_default_preserved_when_chain_empty(self, _clean_env, tmp_path):
        probe = _make_probe_stub({k: False for k in NEUROLOGIST_FALLBACK_CHAIN})
        with patch.object(config_mod, "_probe_provider_reachable", probe):
            cfg = Config.discover(project_dir=tmp_path)
        # Fail-safe — provider stays at the built-in default.
        # YAML may have changed it but it must not be empty / crashed.
        assert cfg.neurologist.provider in {"ollama", "mlx", "deepseek"}
        counters = get_neuro_fallback_counters()
        assert counters["no_provider_reachable"] == 1
        # No provider counter should have incremented.
        for k in ("ollama", "mlx", "mlx_proxy", "deepseek"):
            assert counters[k] == 0


# --- 6. Explicit env var skips fallback -----------------------------------


class TestEnvVarOverrideSkipsFallback:
    def test_env_var_set_no_probe(self, monkeypatch, tmp_path):
        monkeypatch.setenv("CONTEXT_DNA_NEURO_PROVIDER", "deepseek")
        # Even if probe would say ollama is up, env var must dominate.
        probe = _make_probe_stub({k: True for k in NEUROLOGIST_FALLBACK_CHAIN})
        called: list[str] = []

        def _spy_probe(provider_key: str, timeout_s: float = 2.0) -> bool:
            called.append(provider_key)
            return probe(provider_key, timeout_s)

        with patch.object(config_mod, "_probe_provider_reachable", _spy_probe):
            cfg = Config.discover(project_dir=tmp_path)

        # Env var honored…
        assert cfg.neurologist.provider == "deepseek"
        # …and probe never ran (fallback chain gated off by env var).
        assert called == []
        counters = get_neuro_fallback_counters()
        assert counters["default_kept"] == 1
        assert counters["deepseek"] == 0  # not from fallback path


# --- 7. Hard kill-switch --------------------------------------------------


class TestFallbackDisableEnvVar:
    def test_disable_var_skips_chain(self, monkeypatch, tmp_path):
        monkeypatch.delenv("CONTEXT_DNA_NEURO_PROVIDER", raising=False)
        monkeypatch.setenv("CONTEXT_DNA_NEURO_FALLBACK_DISABLE", "1")
        called: list[str] = []

        def _spy_probe(provider_key: str, timeout_s: float = 2.0) -> bool:
            called.append(provider_key)
            return False

        with patch.object(config_mod, "_probe_provider_reachable", _spy_probe):
            cfg = Config.discover(project_dir=tmp_path)

        # Probe never called when kill-switch is engaged.
        assert called == []
        counters = get_neuro_fallback_counters()
        # Neither default_kept nor any provider counter incremented — both
        # branches are gated off.
        assert counters["default_kept"] == 0
        assert counters["no_provider_reachable"] == 0


# --- bonus: real probe path is httpx -------------------------------------


class TestProbeUsesHttpx:
    def test_probe_returns_false_on_connect_error(self, _clean_env):
        # Use a port that is guaranteed closed locally to confirm the probe
        # returns False rather than raising. 1 is reserved (TCPMUX) and
        # almost never bound.
        from three_surgeons.core.config import _probe_provider_reachable
        from three_surgeons.core.config import NEUROLOGIST_PROVIDER_PRESETS

        # Temporarily point the mlx preset at a dead port to exercise the
        # connect-error path without touching live services.
        original = dict(NEUROLOGIST_PROVIDER_PRESETS["mlx"])
        NEUROLOGIST_PROVIDER_PRESETS["mlx"] = {
            **original,
            "endpoint": "http://127.0.0.1:1/v1",
        }
        try:
            assert _probe_provider_reachable("mlx", timeout_s=0.5) is False
        finally:
            NEUROLOGIST_PROVIDER_PRESETS["mlx"] = original

    def test_probe_unknown_provider_returns_false(self, _clean_env):
        from three_surgeons.core.config import _probe_provider_reachable
        assert _probe_provider_reachable("nonexistent-provider") is False

    def test_probe_deepseek_no_key_returns_false(self, _clean_env):
        # _clean_env already strips DeepSeek env vars. Keychain may still
        # have a hit on the dev mac, so patch get_api_key to None to make
        # the test deterministic.
        from three_surgeons.core.config import _probe_provider_reachable, SurgeonConfig
        with patch.object(SurgeonConfig, "get_api_key", return_value=None):
            assert _probe_provider_reachable("deepseek") is False

    def test_probe_deepseek_with_key_returns_true(self, _clean_env, monkeypatch):
        monkeypatch.setenv("Context_DNA_Deepseek", "x" * 32)
        from three_surgeons.core.config import _probe_provider_reachable
        assert _probe_provider_reachable("deepseek") is True
