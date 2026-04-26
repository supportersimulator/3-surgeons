"""Verify fallback chains are actually wired through every LLMProvider site.

Race/x flagged a real bug: ``LLMProvider.query`` honours ``fallbacks=`` but
no construction site was passing them. The fallback loop on models.py:206
was unreachable -- on a Cardio (OpenAI) 429 the surgeon went offline
instead of falling through to DeepSeek.

These tests pin the fix so the regression cannot return:

1. ``LLMProvider.query`` calls each fallback when the primary fails.
2. When every provider in the chain fails, the caller gets a clear error
   (the last failure surfaces -- never a silent skip).
3. The Cardio -> DeepSeek path specifically falls through on 429.
4. Every CLI/MCP/gates construction site threads ``fallbacks=`` from the
   YAML config so the machinery is reachable in production code.
"""
from __future__ import annotations

import inspect
import re
from pathlib import Path
from unittest.mock import patch

import pytest

from three_surgeons.core.config import Config, SurgeonConfig
from three_surgeons.core.models import LLMProvider, LLMResponse


# ── 1. Fallback machinery itself ────────────────────────────────────────


class TestFallbackInvocation:
    """Verify LLMProvider.query actually walks the fallback list."""

    def test_primary_failure_triggers_fallback(self) -> None:
        """Mock primary failure -> verify fallback called and its response returned."""
        primary = SurgeonConfig(
            provider="openai",
            endpoint="https://api.openai.com/v1",
            model="gpt-4.1-mini",
            api_key_env="UNSET_KEY_PRIMARY",
        )
        fallback = SurgeonConfig(
            provider="openai",
            endpoint="https://api.deepseek.com/v1",
            model="deepseek-chat",
            api_key_env="UNSET_KEY_FALLBACK",
        )
        provider = LLMProvider(primary, fallbacks=[fallback])

        calls: list[tuple[str, str]] = []

        def fake_single(endpoint, model, *args, **kwargs):  # type: ignore[no-untyped-def]
            calls.append((endpoint, model))
            if model == "gpt-4.1-mini":
                return LLMResponse.error("HTTP 429: Too Many Requests", model=model)
            return LLMResponse(ok=True, content="fallback ok", model=model)

        with patch.object(LLMProvider, "_single_query", side_effect=fake_single):
            resp = provider.query(system="s", prompt="p")

        assert resp.ok is True
        assert resp.content == "fallback ok"
        assert resp.model == "deepseek-chat"
        # Primary tried first, then fallback
        assert calls[0][1] == "gpt-4.1-mini"
        assert any(model == "deepseek-chat" for _, model in calls)

    def test_all_providers_down_returns_clear_error(self) -> None:
        """When primary AND every fallback fail, the last error surfaces -- no silent skip."""
        primary = SurgeonConfig(
            provider="openai", endpoint="https://api.openai.com/v1",
            model="gpt-4.1-mini", api_key_env="UNSET",
        )
        fallback_a = SurgeonConfig(
            provider="openai", endpoint="https://api.deepseek.com/v1",
            model="deepseek-chat", api_key_env="UNSET",
        )
        fallback_b = SurgeonConfig(
            provider="ollama", endpoint="http://localhost:11434/v1",
            model="qwen3:4b", api_key_env="",
        )
        provider = LLMProvider(primary, fallbacks=[fallback_a, fallback_b])

        def all_fail(endpoint, model, *args, **kwargs):  # type: ignore[no-untyped-def]
            return LLMResponse.error(f"HTTP 503: {model} unavailable", model=model)

        with patch.object(LLMProvider, "_single_query", side_effect=all_fail):
            resp = provider.query(system="s", prompt="p")

        assert resp.ok is False, "exhausted chain must surface failure, not return ok"
        assert "503" in resp.content or "unavailable" in resp.content, (
            f"caller deserves the underlying error message, got: {resp.content!r}"
        )

    def test_cardio_429_falls_through_to_deepseek(self) -> None:
        """The specific outage scenario: OpenAI 429 -> DeepSeek picks up the call."""
        cardio_primary = SurgeonConfig(
            provider="openai",
            endpoint="https://api.openai.com/v1",
            model="gpt-4.1-mini",
            api_key_env="Context_DNA_OPENAI",
        )
        deepseek_fallback = SurgeonConfig(
            provider="openai",  # OpenAI-compatible interface
            endpoint="https://api.deepseek.com/v1",
            model="deepseek-chat",
            api_key_env="Context_DNA_Deepseek",
        )
        cardio = LLMProvider(cardio_primary, fallbacks=[deepseek_fallback])

        def cardio_outage(endpoint, model, *args, **kwargs):  # type: ignore[no-untyped-def]
            if "openai.com" in endpoint:
                return LLMResponse.error(
                    "HTTP 429: rate_limit_exceeded - billing exhausted",
                    model=model,
                )
            assert "deepseek.com" in endpoint
            return LLMResponse(ok=True, content="DeepSeek answered", model=model)

        with patch.object(LLMProvider, "_single_query", side_effect=cardio_outage):
            resp = cardio.query(system="s", prompt="p")

        assert resp.ok is True
        assert resp.model == "deepseek-chat"
        assert "DeepSeek" in resp.content


# ── 2. Construction-site wiring (the bug race/x flagged) ────────────────


class TestCliConstructionSitesWireFallbacks:
    """Every LLMProvider construction in cli/main.py must thread fallbacks."""

    def test_make_neuro_threads_fallbacks_from_config(self) -> None:
        from three_surgeons.cli.main import _make_neuro

        cfg = Config()
        cfg.neurologist = SurgeonConfig(
            provider="openai",
            endpoint="https://api.deepseek.com/v1",
            model="deepseek-chat",
            api_key_env="Context_DNA_Deepseek",
            fallbacks=[
                {"provider": "ollama",
                 "endpoint": "http://localhost:11434/v1",
                 "model": "qwen3:4b",
                 "api_key_env": ""},
            ],
        )
        provider = _make_neuro(cfg)
        assert len(provider._fallbacks) == 1, (
            "_make_neuro must thread cfg.neurologist.get_fallback_configs() "
            "or the fallback loop in models.py:206 is unreachable"
        )
        assert provider._fallbacks[0].model == "qwen3:4b"

    def test_make_cardio_threads_fallbacks_from_config(self) -> None:
        from three_surgeons.cli.main import _make_cardio

        cfg = Config()
        cfg.cardiologist = SurgeonConfig(
            provider="openai",
            endpoint="https://api.openai.com/v1",
            model="gpt-4.1-mini",
            api_key_env="Context_DNA_OPENAI",
            fallbacks=[
                {"provider": "openai",
                 "endpoint": "https://api.deepseek.com/v1",
                 "model": "deepseek-chat",
                 "api_key_env": "Context_DNA_Deepseek"},
            ],
        )
        provider = _make_cardio(cfg)
        assert len(provider._fallbacks) == 1
        assert provider._fallbacks[0].model == "deepseek-chat"
        assert provider._fallbacks[0].endpoint == "https://api.deepseek.com/v1"

    def test_no_bare_llmprovider_construction_in_cli(self) -> None:
        """Static guard: every LLMProvider(...) in cli/main.py must pass fallbacks=
        OR delegate to a _make_* helper that threads them. Catches regressions
        where someone re-introduces the bug race/x found."""
        cli_path = Path(__file__).parent.parent / "three_surgeons" / "cli" / "main.py"
        source = cli_path.read_text()
        # Strip the helper definitions themselves -- we check their body separately
        # via `test_make_neuro_threads_fallbacks_from_config` and the cardio variant.
        # Match every other LLMProvider(...) call.
        pattern = re.compile(r"LLMProvider\([^)]*\)")
        offenders: list[str] = []
        for m in pattern.finditer(source):
            call = m.group(0)
            if "fallbacks=" in call:
                continue
            # Allow bare construction only inside the _make_* helpers (they wrap
            # the call themselves) -- detect by checking the surrounding function.
            line_no = source[:m.start()].count("\n") + 1
            offenders.append(f"line {line_no}: {call}")
        assert not offenders, (
            "Bare LLMProvider() calls re-introduce the fallback bug. "
            "Use _make_cardio/_make_neuro or pass fallbacks=cfg.get_fallback_configs():\n"
            + "\n".join(offenders)
        )


class TestMcpServerConstructionSitesWireFallbacks:
    """Every LLMProvider construction in mcp/server.py must thread fallbacks."""

    def test_no_bare_llmprovider_construction_in_mcp(self) -> None:
        mcp_path = Path(__file__).parent.parent / "three_surgeons" / "mcp" / "server.py"
        source = mcp_path.read_text()
        pattern = re.compile(r"LLMProvider\([^)]*\)")
        offenders: list[str] = []
        for m in pattern.finditer(source):
            call = m.group(0)
            if "fallbacks=" in call:
                continue
            line_no = source[:m.start()].count("\n") + 1
            offenders.append(f"line {line_no}: {call}")
        assert not offenders, (
            "Bare LLMProvider() in mcp/server.py — wire fallbacks=:\n"
            + "\n".join(offenders)
        )


class TestGatesConstructionSitesWireFallbacks:
    """gates.py runs in the gains-gate hot path -- must wire fallbacks too."""

    def test_no_bare_llmprovider_construction_in_gates(self) -> None:
        gates_path = Path(__file__).parent.parent / "three_surgeons" / "core" / "gates.py"
        source = gates_path.read_text()
        pattern = re.compile(r"LLMProvider\([^)]*\)")
        offenders: list[str] = []
        for m in pattern.finditer(source):
            call = m.group(0)
            if "fallbacks=" in call:
                continue
            line_no = source[:m.start()].count("\n") + 1
            offenders.append(f"line {line_no}: {call}")
        assert not offenders, (
            "Bare LLMProvider() in core/gates.py — wire fallbacks=:\n"
            + "\n".join(offenders)
        )


class TestContextBuilderConstructionWiresFallbacks:
    def test_no_bare_llmprovider_construction_in_context_builder(self) -> None:
        path = Path(__file__).parent.parent / "three_surgeons" / "core" / "context_builder.py"
        source = path.read_text()
        pattern = re.compile(r"LLMProvider\([^)]*\)")
        offenders: list[str] = []
        for m in pattern.finditer(source):
            call = m.group(0)
            if "fallbacks=" in call:
                continue
            line_no = source[:m.start()].count("\n") + 1
            offenders.append(f"line {line_no}: {call}")
        assert not offenders, (
            "Bare LLMProvider() in core/context_builder.py — wire fallbacks=:\n"
            + "\n".join(offenders)
        )


# ── 3. Config plumbing: YAML fallbacks survive the merge layer ──────────


class TestConfigYamlFallbacksSurviveMerge:
    """Config.from_yaml must preserve fallback lists -- Config layer is part of
    the wiring chain. If merge drops them, every CLI helper above is moot."""

    def test_yaml_fallbacks_round_trip(self, tmp_path: Path) -> None:
        import yaml as _yaml
        config_data = {
            "surgeons": {
                "cardiologist": {
                    "provider": "openai",
                    "endpoint": "https://api.openai.com/v1",
                    "model": "gpt-4.1-mini",
                    "api_key_env": "Context_DNA_OPENAI",
                    "fallbacks": [
                        {"provider": "openai",
                         "endpoint": "https://api.deepseek.com/v1",
                         "model": "deepseek-chat",
                         "api_key_env": "Context_DNA_Deepseek"},
                    ],
                },
            },
        }
        path = tmp_path / "config.yaml"
        path.write_text(_yaml.dump(config_data))

        cfg = Config.from_yaml(path)
        fbs = cfg.cardiologist.get_fallback_configs()
        assert len(fbs) == 1
        assert fbs[0].provider == "openai"
        assert fbs[0].endpoint == "https://api.deepseek.com/v1"
        assert fbs[0].model == "deepseek-chat"
        assert fbs[0].api_key_env == "Context_DNA_Deepseek"
