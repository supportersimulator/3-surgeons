"""Tests for the LLM provider abstraction layer."""
from __future__ import annotations

from three_surgeons.core.config import SurgeonConfig
from three_surgeons.core.models import LLMProvider, LLMResponse, create_provider, estimate_cost


class TestResponseFields:
    """Test LLMResponse dataclass construction and field access."""

    def test_response_fields(self) -> None:
        """Create LLMResponse with all fields, verify each is stored correctly."""
        resp = LLMResponse(
            ok=True,
            content="Hello world",
            latency_ms=150,
            model="gpt-4.1-mini",
            cost_usd=0.001,
            tokens_in=50,
            tokens_out=20,
        )
        assert resp.ok is True
        assert resp.content == "Hello world"
        assert resp.latency_ms == 150
        assert resp.model == "gpt-4.1-mini"
        assert resp.cost_usd == 0.001
        assert resp.tokens_in == 50
        assert resp.tokens_out == 20

    def test_response_defaults(self) -> None:
        """Create LLMResponse with only required fields, verify defaults."""
        resp = LLMResponse(ok=True, content="ok")
        assert resp.latency_ms == 0
        assert resp.model == ""
        assert resp.cost_usd == 0.0
        assert resp.tokens_in == 0
        assert resp.tokens_out == 0


class TestFailedResponse:
    """Test the LLMResponse.error() class method."""

    def test_failed_response(self) -> None:
        """LLMResponse.error() returns ok=False with the error message as content."""
        resp = LLMResponse.error("connection refused", model="gpt-4.1-mini")
        assert resp.ok is False
        assert resp.content == "connection refused"
        assert resp.model == "gpt-4.1-mini"

    def test_failed_response_default_model(self) -> None:
        """LLMResponse.error() with no model defaults to empty string."""
        resp = LLMResponse.error("timeout")
        assert resp.ok is False
        assert resp.content == "timeout"
        assert resp.model == ""


class TestCreateOpenAIProvider:
    """Test creating a provider from an OpenAI-style SurgeonConfig."""

    def test_create_openai_provider(self) -> None:
        """Create LLMProvider from OpenAI config, verify model and endpoint."""
        config = SurgeonConfig(
            provider="openai",
            endpoint="https://api.openai.com/v1",
            model="gpt-4.1-mini",
            api_key_env="Context_DNA_OPENAI",
            role="test",
        )
        provider = create_provider(config)
        assert isinstance(provider, LLMProvider)
        assert provider.model == "gpt-4.1-mini"
        assert provider.endpoint == "https://api.openai.com/v1"
        assert provider._is_local is False


class TestCreateOllamaProvider:
    """Test creating a provider from an Ollama-style SurgeonConfig."""

    def test_create_ollama_provider(self) -> None:
        """Create LLMProvider from ollama config, verify fields and _is_local."""
        config = SurgeonConfig(
            provider="ollama",
            endpoint="http://localhost:11434/v1",
            model="qwen3:4b",
            api_key_env="",
            role="local",
        )
        provider = create_provider(config)
        assert isinstance(provider, LLMProvider)
        assert provider.model == "qwen3:4b"
        assert provider.endpoint == "http://localhost:11434/v1"
        assert provider._is_local is True


class TestCostCalculation:
    """Test the estimate_cost function."""

    def test_openai_cost_calculation(self) -> None:
        """estimate_cost for gpt-4.1-mini with known token counts.

        Pricing: (0.40, 1.60) per 1M tokens.
        1000 tokens in  = 1000 * 0.40 / 1_000_000 = 0.0004
        500 tokens out  = 500 * 1.60 / 1_000_000 = 0.0008
        Total = 0.0012
        """
        cost = estimate_cost("gpt-4.1-mini", tokens_in=1000, tokens_out=500)
        assert cost == pytest.approx(0.0012)

    def test_local_model_zero_cost(self) -> None:
        """estimate_cost for qwen3:4b (unknown/local model) returns 0.0."""
        cost = estimate_cost("qwen3:4b", tokens_in=5000, tokens_out=2000)
        assert cost == 0.0

    def test_gpt41_cost(self) -> None:
        """estimate_cost for gpt-4.1 with known token counts.

        Pricing: (2.00, 8.00) per 1M tokens.
        1000 tokens in  = 1000 * 2.00 / 1_000_000 = 0.002
        1000 tokens out = 1000 * 8.00 / 1_000_000 = 0.008
        Total = 0.010
        """
        cost = estimate_cost("gpt-4.1", tokens_in=1000, tokens_out=1000)
        assert cost == pytest.approx(0.010)

    def test_zero_tokens_zero_cost(self) -> None:
        """estimate_cost with zero tokens returns 0.0 even for known models."""
        cost = estimate_cost("gpt-4.1-mini", tokens_in=0, tokens_out=0)
        assert cost == 0.0


class TestProviderEndpointStripping:
    """Test that trailing slashes are stripped from endpoints."""

    def test_trailing_slash_stripped(self) -> None:
        """Endpoint with trailing slash should have it removed."""
        config = SurgeonConfig(
            provider="openai",
            endpoint="https://api.openai.com/v1/",
            model="gpt-4.1-mini",
            api_key_env="Context_DNA_OPENAI",
            role="test",
        )
        provider = create_provider(config)
        assert provider.endpoint == "https://api.openai.com/v1"


# Need pytest import for approx
import pytest


def test_deepseek_pricing():
    from three_surgeons.core.models import estimate_cost
    cost = estimate_cost("deepseek-chat", 1_000_000, 1_000_000)
    assert cost > 0
    assert abs(cost - 1.37) < 0.01  # 0.27 + 1.10


def test_groq_pricing():
    from three_surgeons.core.models import estimate_cost
    cost = estimate_cost("llama-3.3-70b-versatile", 1_000_000, 1_000_000)
    assert cost > 0
    assert abs(cost - 1.38) < 0.01  # 0.59 + 0.79


def test_grok_pricing():
    from three_surgeons.core.models import estimate_cost
    cost = estimate_cost("grok-2", 1_000_000, 1_000_000)
    assert cost > 0
    assert abs(cost - 12.00) < 0.01  # 2.00 + 10.00


def test_mistral_pricing():
    from three_surgeons.core.models import estimate_cost
    cost = estimate_cost("mistral-large-latest", 1_000_000, 1_000_000)
    assert cost > 0
    assert abs(cost - 8.00) < 0.01  # 2.00 + 6.00


# ── Think-tag stripping ─────────────────────────────────────────────


from three_surgeons.core.models import strip_think_tags


class TestStripThinkTags:
    """strip_think_tags removes Qwen3-style reasoning blocks."""

    def test_closed_think_tags(self) -> None:
        raw = '<think>\nLet me reason about this...\n</think>\n{"verdict": "ok"}'
        assert strip_think_tags(raw) == '{"verdict": "ok"}'

    def test_unclosed_think_tag(self) -> None:
        raw = "<think>\nI'm still thinking and the budget ran out..."
        assert strip_think_tags(raw) == ""

    def test_no_think_tags(self) -> None:
        raw = '{"verdict": "ok", "confidence": 0.9}'
        assert strip_think_tags(raw) == raw

    def test_empty_think_tags(self) -> None:
        raw = "<think></think>\nclean output"
        assert strip_think_tags(raw) == "clean output"

    def test_think_with_multiline_json(self) -> None:
        raw = (
            "<think>\nAnalyzing the evidence...\nChecking grades...\n</think>\n"
            '[\n  {"claim": "test", "challenge": "why?", "severity": "critical"}\n]'
        )
        result = strip_think_tags(raw)
        assert result.startswith("[")
        assert '"claim": "test"' in result

    def test_preserves_content_before_think(self) -> None:
        raw = "prefix <think>reasoning</think> suffix"
        assert strip_think_tags(raw) == "prefix suffix"


# ── QueryAdapter protocol ───────────────────────────────────────────


class TestQueryAdapter:
    """QueryAdapter enables routing LLM calls through custom backends."""

    def _make_provider(self, *, adapter=None, is_local: bool = False) -> LLMProvider:
        provider_name = "mlx" if is_local else "openai"
        config = SurgeonConfig(
            provider=provider_name,
            endpoint="http://127.0.0.1:9999/v1",
            model="test-model",
            api_key_env="",
            role="test",
        )
        return LLMProvider(config, query_adapter=adapter)

    def test_no_adapter_uses_http(self) -> None:
        """Without adapter, provider uses default HTTP path."""
        provider = self._make_provider()
        assert provider._adapter is None

    def test_adapter_receives_all_params(self) -> None:
        """Adapter callable receives system, prompt, max_tokens, temperature, timeout_s."""
        captured = {}

        def fake_adapter(system, prompt, max_tokens, temperature, timeout_s):
            captured.update(locals())
            return LLMResponse(ok=True, content="from adapter", model="adapted")

        provider = self._make_provider(adapter=fake_adapter)
        resp = provider.query(system="sys", prompt="usr", max_tokens=512, temperature=0.3, timeout_s=10.0)
        assert resp.ok is True
        assert resp.content == "from adapter"
        assert captured["system"] == "sys"
        assert captured["prompt"] == "usr"
        assert captured["max_tokens"] == 512
        assert captured["temperature"] == 0.3
        assert captured["timeout_s"] == 10.0

    def test_adapter_bypasses_http(self) -> None:
        """When adapter is set, no HTTP call is made (even to invalid endpoint)."""
        def fake_adapter(system, prompt, max_tokens, temperature, timeout_s):
            return LLMResponse(ok=True, content="routed", model="queue")

        # Endpoint is unreachable — but adapter prevents HTTP call
        provider = self._make_provider(adapter=fake_adapter)
        resp = provider.query(system="s", prompt="p")
        assert resp.ok is True
        assert resp.content == "routed"

    def test_adapter_think_tags_still_stripped_for_local(self) -> None:
        """Think-tag stripping applies to adapter responses for local models."""
        def think_adapter(system, prompt, max_tokens, temperature, timeout_s):
            return LLMResponse(
                ok=True,
                content='<think>\nreasoning\n</think>\n{"result": "clean"}',
                model="local-qwen",
            )

        provider = self._make_provider(adapter=think_adapter, is_local=True)
        resp = provider.query(system="s", prompt="p")
        assert resp.ok is True
        assert "<think>" not in resp.content
        assert '{"result": "clean"}' == resp.content

    def test_adapter_no_strip_for_remote(self) -> None:
        """Think-tag stripping does NOT apply for remote providers (even if content has tags)."""
        def remote_adapter(system, prompt, max_tokens, temperature, timeout_s):
            return LLMResponse(
                ok=True,
                content="<think>some reasoning</think>\nresult",
                model="gpt-4.1",
            )

        provider = self._make_provider(adapter=remote_adapter, is_local=False)
        resp = provider.query(system="s", prompt="p")
        assert "<think>" in resp.content  # Not stripped for remote

    def test_adapter_error_propagated(self) -> None:
        """Adapter returning ok=False propagates cleanly."""
        def failing_adapter(system, prompt, max_tokens, temperature, timeout_s):
            return LLMResponse.error("queue full", model="local")

        provider = self._make_provider(adapter=failing_adapter)
        resp = provider.query(system="s", prompt="p")
        assert resp.ok is False
        assert "queue full" in resp.content

    def test_adapter_exception_caught(self) -> None:
        """If adapter raises, LLMProvider catches and returns error response."""
        def broken_adapter(system, prompt, max_tokens, temperature, timeout_s):
            raise RuntimeError("adapter crashed")

        provider = self._make_provider(adapter=broken_adapter)
        resp = provider.query(system="s", prompt="p")
        assert resp.ok is False
        assert "adapter crashed" in resp.content

    def test_ping_routes_through_adapter(self) -> None:
        """ping() also routes through adapter when present."""
        def ping_adapter(system, prompt, max_tokens, temperature, timeout_s):
            return LLMResponse(ok=True, content="operational", model="adapted")

        provider = self._make_provider(adapter=ping_adapter)
        resp = provider.ping()
        assert resp.ok is True
        assert resp.content == "operational"
