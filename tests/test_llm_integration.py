"""Integration tests for real LLM endpoints (OpenAI, DeepSeek, local MLX).

These tests hit live APIs and are excluded from the default test run.
Run explicitly with: pytest -m integration tests/test_llm_integration.py

API keys are loaded from environment variables:
  Context_DNA_OPENAI   - OpenAI API (cardiologist default)
  Context_DNA_Deepseek - DeepSeek API (alternative external provider)

For local MLX tests, the server must be running on port 5044.
"""
from __future__ import annotations

import os

import pytest

from three_surgeons.core.config import SurgeonConfig
from three_surgeons.core.models import LLMProvider, LLMResponse

# All tests in this file require the integration marker
pytestmark = pytest.mark.integration


# ── Fixtures ────────────────────────────────────────────────────────────


@pytest.fixture
def openai_provider() -> LLMProvider:
    """Create an OpenAI LLMProvider using Context_DNA_OPENAI from environment."""
    key = os.environ.get("Context_DNA_OPENAI")
    if not key or len(key) < 6:
        pytest.skip("Context_DNA_OPENAI not set")
    config = SurgeonConfig(
        provider="openai",
        endpoint="https://api.openai.com/v1",
        model="gpt-4.1-mini",
        api_key_env="Context_DNA_OPENAI",
        role="Integration test cardiologist",
    )
    return LLMProvider(config)


@pytest.fixture
def deepseek_provider() -> LLMProvider:
    """Create a DeepSeek LLMProvider using Context_DNA_Deepseek from environment."""
    key = os.environ.get("Context_DNA_Deepseek")
    if not key or len(key) < 6:
        pytest.skip("Context_DNA_Deepseek not set")
    config = SurgeonConfig(
        provider="deepseek",
        endpoint="https://api.deepseek.com/v1",
        model="deepseek-chat",
        api_key_env="Context_DNA_Deepseek",
        role="Integration test DeepSeek provider",
    )
    return LLMProvider(config)


@pytest.fixture
def mlx_provider() -> LLMProvider:
    """Create a local MLX LLMProvider (port 5044)."""
    import httpx

    try:
        resp = httpx.get("http://127.0.0.1:5044/v1/models", timeout=2.0)
        if resp.status_code != 200:
            pytest.skip("MLX server not responding on port 5044")
    except (httpx.ConnectError, httpx.TimeoutException):
        pytest.skip("MLX server not running on port 5044")

    models = resp.json().get("data", [])
    model_id = models[0]["id"] if models else "default"

    config = SurgeonConfig(
        provider="mlx",
        endpoint="http://127.0.0.1:5044/v1",
        model=model_id,
        api_key_env="",
        role="Integration test neurologist (MLX)",
    )
    return LLMProvider(config)


# ── OpenAI Tests ────────────────────────────────────────────────────────


class TestOpenAIIntegration:
    """Tests against the live OpenAI API."""

    def test_openai_ping(self, openai_provider: LLMProvider):
        """OpenAI endpoint responds to health check."""
        resp = openai_provider.ping(timeout_s=15.0)
        assert resp.ok, f"OpenAI ping failed: {resp.content}"
        assert "operational" in resp.content.lower()

    def test_openai_query(self, openai_provider: LLMProvider):
        """OpenAI returns a coherent response to a simple prompt."""
        resp = openai_provider.query(
            system="You are a helpful assistant. Reply in exactly one sentence.",
            prompt="What is 2 + 2?",
            max_tokens=64,
            temperature=0.0,
            timeout_s=15.0,
        )
        assert resp.ok, f"OpenAI query failed: {resp.content}"
        assert "4" in resp.content
        assert resp.tokens_in > 0
        assert resp.tokens_out > 0
        assert resp.cost_usd > 0

    def test_openai_cost_tracking(self, openai_provider: LLMProvider):
        """OpenAI responses include valid cost estimates."""
        resp = openai_provider.query(
            system="Reply with one word.",
            prompt="Say hello.",
            max_tokens=16,
            temperature=0.0,
            timeout_s=15.0,
        )
        assert resp.ok
        assert resp.cost_usd > 0
        assert resp.cost_usd < 0.01  # sanity: one-word response should be cheap


# ── DeepSeek Tests ──────────────────────────────────────────────────────


class TestDeepSeekIntegration:
    """Tests against the live DeepSeek API."""

    def test_deepseek_ping(self, deepseek_provider: LLMProvider):
        """DeepSeek endpoint responds to health check."""
        resp = deepseek_provider.ping(timeout_s=15.0)
        assert resp.ok, f"DeepSeek ping failed: {resp.content}"
        assert "operational" in resp.content.lower()

    def test_deepseek_query(self, deepseek_provider: LLMProvider):
        """DeepSeek returns a coherent response."""
        resp = deepseek_provider.query(
            system="You are a helpful assistant. Reply in exactly one sentence.",
            prompt="What is the capital of France?",
            max_tokens=64,
            temperature=0.0,
            timeout_s=30.0,
        )
        assert resp.ok, f"DeepSeek query failed: {resp.content}"
        assert "paris" in resp.content.lower()

    def test_deepseek_cost_tracking(self, deepseek_provider: LLMProvider):
        """DeepSeek responses include valid cost estimates."""
        resp = deepseek_provider.query(
            system="Reply with one word.",
            prompt="Say hello.",
            max_tokens=16,
            temperature=0.0,
            timeout_s=30.0,
        )
        assert resp.ok
        assert resp.cost_usd > 0
        assert resp.cost_usd < 0.01


# ── Local MLX Tests ─────────────────────────────────────────────────────


class TestMLXIntegration:
    """Tests against the local MLX server (port 5044)."""

    def test_mlx_ping(self, mlx_provider: LLMProvider):
        """MLX endpoint responds to health check."""
        resp = mlx_provider.ping(timeout_s=30.0)
        assert resp.ok, f"MLX ping failed: {resp.content}"

    def test_mlx_query(self, mlx_provider: LLMProvider):
        """MLX returns a response (may include think tags, stripped automatically)."""
        resp = mlx_provider.query(
            system="Reply in one sentence.",
            prompt="What is 1 + 1?",
            max_tokens=128,
            temperature=0.0,
            timeout_s=60.0,
        )
        assert resp.ok, f"MLX query failed: {resp.content}"
        assert "<think>" not in resp.content  # think tags should be stripped
        assert resp.cost_usd == 0.0  # local model = free

    def test_mlx_zero_cost(self, mlx_provider: LLMProvider):
        """Local MLX calls report zero cost."""
        resp = mlx_provider.query(
            system="Reply with one word.",
            prompt="Say yes.",
            max_tokens=16,
            timeout_s=30.0,
        )
        assert resp.ok
        assert resp.cost_usd == 0.0


# ── Cross-Provider Fallback Tests ───────────────────────────────────────


class TestProviderFallback:
    """Test fallback behavior between providers."""

    def test_fallback_from_bad_endpoint_to_openai(self):
        """LLMProvider falls back when primary endpoint is unreachable."""
        key = os.environ.get("Context_DNA_OPENAI")
        if not key or len(key) < 6:
            pytest.skip("Context_DNA_OPENAI not set")

        bad_config = SurgeonConfig(
            provider="openai",
            endpoint="http://127.0.0.1:19999/v1",  # unreachable port
            model="fake-model",
            api_key_env="",
        )
        fallback_config = SurgeonConfig(
            provider="openai",
            endpoint="https://api.openai.com/v1",
            model="gpt-4.1-mini",
            api_key_env="Context_DNA_OPENAI",
        )
        provider = LLMProvider(bad_config, fallbacks=[fallback_config])
        resp = provider.query(
            system="Reply with one word.",
            prompt="Say hello.",
            max_tokens=16,
            timeout_s=15.0,
        )
        assert resp.ok, f"Fallback failed: {resp.content}"
