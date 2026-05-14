"""AAA1 2026-05-12 — Tests for the cardiologist auto-fallback chain.

Mirrors ``test_neurologist_fallback.py`` (QQ1) for the cardiologist.

Bug being prevented (RR5 / WW5 / ZZ5): when Anthropic billing is inactive
and cardiologist is hard-pinned to anthropic, ``3s consensus`` collapses
to a single cloud surgeon (both cardio and neuro fall to DeepSeek) →
zero model diversity → sycophancy. The fallback chain silently upgrades
the cardiologist to the next reachable provider so the 3-surgeon
invariant is preserved without an env-var flip.

Contract pinned by this module:

    1. Healthy node (all keys present) → openai wins, default unchanged.
    2. openai-key missing + anthropic-key present → anthropic wins; counter +1.
    3. openai+anthropic missing + deepseek key → deepseek wins.
    4. No keys for any provider → no_provider_reachable +1; default kept.
    5. CONTEXT_DNA_CARDIO_PROVIDER set → no fallback runs; default_kept +1.
    6. Bogus CONTEXT_DNA_CARDIO_PROVIDER → ZSF, falls back to default.
    7. CONTEXT_DNA_CARDIO_FALLBACK_DISABLE=1 → no fallback runs.

Probe is monkey-patched at the ``_probe_cardio_provider_reachable`` seam
so tests are network-free and deterministic.
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

import pytest

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from three_surgeons.core import config as config_mod  # noqa: E402
from three_surgeons.core.config import (  # noqa: E402
    CARDIOLOGIST_FALLBACK_CHAIN,
    Config,
    get_cardio_fallback_counters,
    reset_cardio_fallback_counters,
)


# --- probe-stub helpers ----------------------------------------------------


def _make_probe_stub(reachable: dict[str, bool]):
    """Return a fake _probe_cardio_provider_reachable that uses ``reachable``."""

    def _stub(provider_key: str, timeout_s: float = 2.0) -> bool:
        return reachable.get(provider_key, False)

    return _stub


@pytest.fixture(autouse=True)
def _isolate_counters():
    """Each test starts with zeroed counters so assertions are local."""
    reset_cardio_fallback_counters()
    yield
    reset_cardio_fallback_counters()


# --- 1. Healthy node ------------------------------------------------------


class TestHealthyNodePreservesDefault:
    def test_deepseek_up_wins_first(self, tmp_path):
        # WaveR 2026-05-12: chain flipped to [deepseek, anthropic, openai] —
        # deepseek wins when all healthy. Preserves new free-CC default.
        probe = _make_probe_stub({k: True for k in CARDIOLOGIST_FALLBACK_CHAIN})
        with patch.object(config_mod, "_probe_cardio_provider_reachable", probe):
            cfg = Config.discover(project_dir=tmp_path)
        assert cfg.cardiologist.provider == "deepseek"
        assert cfg.cardiologist.endpoint == "https://api.deepseek.com/v1"
        assert cfg.cardiologist.model == "deepseek-chat"
        counters = get_cardio_fallback_counters()
        assert counters["deepseek"] == 1
        # No other branch fired.
        for k in ("anthropic", "openai", "no_provider_reachable"):
            assert counters[k] == 0


# --- 2. deepseek down, anthropic up ---------------------------------------


class TestDeepSeekDownAnthropicUp:
    def test_falls_back_to_anthropic(self, tmp_path):
        # Chain [deepseek, anthropic, openai] — deepseek down skips to
        # anthropic (chain index 1). Updated for WaveR 2026-05-12 flip.
        probe = _make_probe_stub({
            "deepseek": False,
            "anthropic": True,
            "openai": True,
        })
        with patch.object(config_mod, "_probe_cardio_provider_reachable", probe):
            cfg = Config.discover(project_dir=tmp_path)
        assert cfg.cardiologist.provider == "anthropic"
        assert cfg.cardiologist.endpoint == "https://api.anthropic.com/v1"
        counters = get_cardio_fallback_counters()
        assert counters["anthropic"] == 1
        assert counters["deepseek"] == 0


# --- 3. openai + anthropic down, deepseek up ------------------------------


class TestDeepSeekFallback:
    def test_falls_back_to_deepseek(self, tmp_path):
        probe = _make_probe_stub({
            "openai": False,
            "anthropic": False,
            "deepseek": True,
        })
        with patch.object(config_mod, "_probe_cardio_provider_reachable", probe):
            cfg = Config.discover(project_dir=tmp_path)
        assert cfg.cardiologist.provider == "deepseek"
        assert cfg.cardiologist.endpoint == "https://api.deepseek.com/v1"
        assert cfg.cardiologist.model == "deepseek-chat"
        counters = get_cardio_fallback_counters()
        assert counters["deepseek"] == 1


# --- 4. all providers unreachable, fail-safe ------------------------------


class TestNoProviderReachable:
    def test_default_preserved_when_chain_empty(self, tmp_path):
        probe = _make_probe_stub({k: False for k in CARDIOLOGIST_FALLBACK_CHAIN})
        with patch.object(config_mod, "_probe_cardio_provider_reachable", probe):
            cfg = Config.discover(project_dir=tmp_path)
        # Fail-safe — provider stays at the built-in default rather than
        # crashing. Real systems can still emit a friendly "cardiologist
        # unavailable" downstream.
        assert cfg.cardiologist.provider in {"openai", "anthropic", "deepseek"}
        counters = get_cardio_fallback_counters()
        assert counters["no_provider_reachable"] == 1
        # No provider counter should have incremented.
        for k in ("openai", "anthropic", "deepseek"):
            assert counters[k] == 0


# --- 5. Explicit env var skips fallback -----------------------------------


class TestEnvVarOverrideSkipsFallback:
    def test_env_var_set_no_probe(self, monkeypatch, tmp_path):
        monkeypatch.setenv("CONTEXT_DNA_CARDIO_PROVIDER", "deepseek")
        # Even if probe would say openai is up, env var must dominate.
        probe = _make_probe_stub({k: True for k in CARDIOLOGIST_FALLBACK_CHAIN})
        called: list[str] = []

        def _spy_probe(provider_key: str, timeout_s: float = 2.0) -> bool:
            called.append(provider_key)
            return probe(provider_key, timeout_s)

        with patch.object(config_mod, "_probe_cardio_provider_reachable", _spy_probe):
            cfg = Config.discover(project_dir=tmp_path)

        # Env var honored…
        assert cfg.cardiologist.provider == "deepseek"
        # …and probe never ran (fallback chain gated off by env var).
        assert called == []
        counters = get_cardio_fallback_counters()
        assert counters["default_kept"] == 1
        assert counters["deepseek"] == 0  # not from fallback path


# --- 6. Bogus env var → ZSF, default preserved ----------------------------


class TestBogusEnvVarZSF:
    def test_bogus_provider_does_not_crash(self, monkeypatch, tmp_path):
        monkeypatch.setenv("CONTEXT_DNA_CARDIO_PROVIDER", "not-a-real-provider")
        # Probe should be skipped (env var path taken) — provider stays at
        # whatever default _default_cardiologist() picked, no crash.
        called: list[str] = []

        def _spy_probe(provider_key: str, timeout_s: float = 2.0) -> bool:
            called.append(provider_key)
            return True

        with patch.object(config_mod, "_probe_cardio_provider_reachable", _spy_probe):
            cfg = Config.discover(project_dir=tmp_path)

        # discover() did not crash; cardio kept its built-in default.
        assert cfg.cardiologist.provider in {"openai", "anthropic", "deepseek"}
        # Probe never ran — env-var branch was taken.
        assert called == []
        # Counter still bumped (env-var branch always increments default_kept,
        # parity with the neuro chain).
        counters = get_cardio_fallback_counters()
        assert counters["default_kept"] == 1


# --- 7. Hard kill-switch --------------------------------------------------


class TestFallbackDisableEnvVar:
    def test_disable_var_skips_chain(self, monkeypatch, tmp_path):
        monkeypatch.delenv("CONTEXT_DNA_CARDIO_PROVIDER", raising=False)
        monkeypatch.setenv("CONTEXT_DNA_CARDIO_FALLBACK_DISABLE", "1")
        called: list[str] = []

        def _spy_probe(provider_key: str, timeout_s: float = 2.0) -> bool:
            called.append(provider_key)
            return False

        with patch.object(config_mod, "_probe_cardio_provider_reachable", _spy_probe):
            cfg = Config.discover(project_dir=tmp_path)

        # Probe never called when kill-switch is engaged.
        assert called == []
        counters = get_cardio_fallback_counters()
        # Neither default_kept nor any provider counter incremented — both
        # branches are gated off.
        assert counters["default_kept"] == 0
        assert counters["no_provider_reachable"] == 0


# --- bonus: real probe path ---------------------------------------------


class TestProbeReachability:
    def test_probe_unknown_provider_returns_false(self):
        from three_surgeons.core.config import _probe_cardio_provider_reachable
        assert _probe_cardio_provider_reachable("nonexistent-provider") is False

    def test_probe_no_key_returns_false(self):
        # isolate_env already strips all cardio API keys + stubs keychain.
        from three_surgeons.core.config import _probe_cardio_provider_reachable
        assert _probe_cardio_provider_reachable("openai") is False
        assert _probe_cardio_provider_reachable("anthropic") is False
        assert _probe_cardio_provider_reachable("deepseek") is False

    def test_probe_with_openai_key_returns_true(self, monkeypatch):
        monkeypatch.setenv("Context_DNA_OPENAI", "x" * 32)
        from three_surgeons.core.config import _probe_cardio_provider_reachable
        assert _probe_cardio_provider_reachable("openai") is True

    def test_probe_with_anthropic_key_returns_true(self, monkeypatch):
        monkeypatch.setenv("Context_DNA_Anthropic", "x" * 32)
        from three_surgeons.core.config import _probe_cardio_provider_reachable
        assert _probe_cardio_provider_reachable("anthropic") is True

    def test_probe_with_deepseek_key_returns_true(self, monkeypatch):
        monkeypatch.setenv("Context_DNA_Deepseek", "x" * 32)
        from three_surgeons.core.config import _probe_cardio_provider_reachable
        assert _probe_cardio_provider_reachable("deepseek") is True
