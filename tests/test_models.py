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
            api_key_env="OPENAI_API_KEY",
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
            api_key_env="OPENAI_API_KEY",
            role="test",
        )
        provider = create_provider(config)
        assert provider.endpoint == "https://api.openai.com/v1"


# Need pytest import for approx
import pytest
