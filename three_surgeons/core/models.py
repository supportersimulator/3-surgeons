"""LLM provider abstraction with OpenAI-compatible interface.

All providers (OpenAI, Ollama, local MLX) use the same /v1/chat/completions
interface. This module provides a unified LLMProvider that handles construction,
querying, cost estimation, and error handling.
"""
from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from typing import Callable, Dict, Optional, Protocol, Tuple, runtime_checkable

import httpx

from three_surgeons.core.config import SurgeonConfig

# Pricing per 1M tokens: (input_usd, output_usd)
_THINK_RE = re.compile(r"<think>.*?</think>\s*", re.DOTALL)
_THINK_UNCLOSED_RE = re.compile(r"<think>.*", re.DOTALL)


def strip_think_tags(text: str) -> str:
    """Remove Qwen3-style <think>...</think> reasoning blocks from LLM output.

    Handles both closed tags and unclosed tags (when token budget runs out
    before the model can emit </think>).
    """
    if "<think>" not in text:
        return text
    # Closed tags first
    result = _THINK_RE.sub("", text)
    # Unclosed tag (budget exhausted mid-thought)
    result = _THINK_UNCLOSED_RE.sub("", result)
    return result.strip()


PRICING: Dict[str, Tuple[float, float]] = {
    # OpenAI
    "gpt-4.1": (2.00, 8.00),
    "gpt-4.1-mini": (0.40, 1.60),
    "gpt-4.1-nano": (0.10, 0.40),
    "o3": (2.00, 8.00),
    "o4-mini": (1.10, 4.40),
    # DeepSeek
    "deepseek-chat": (0.27, 1.10),
    "deepseek-reasoner": (0.55, 2.19),
    # Groq (hosted models)
    "llama-3.3-70b-versatile": (0.59, 0.79),
    "llama-3.1-8b-instant": (0.05, 0.08),
    # Mistral
    "mistral-large-latest": (2.00, 6.00),
    "mistral-small-latest": (0.10, 0.30),
    # xAI (Grok)
    "grok-2": (2.00, 10.00),
    "grok-2-mini": (0.30, 0.50),
}


def estimate_cost(model: str, tokens_in: int, tokens_out: int) -> float:
    """Estimate the cost of an LLM call in USD.

    Returns 0.0 for unknown or local models not in the PRICING table.
    """
    if model not in PRICING:
        return 0.0
    input_rate, output_rate = PRICING[model]
    return (tokens_in * input_rate + tokens_out * output_rate) / 1_000_000


@dataclass
class LLMResponse:
    """Structured response from an LLM provider call."""

    ok: bool
    content: str
    latency_ms: int = 0
    model: str = ""
    cost_usd: float = 0.0
    tokens_in: int = 0
    tokens_out: int = 0

    @classmethod
    def error(cls, message: str, model: str = "") -> LLMResponse:
        """Create an error response with ok=False."""
        return cls(ok=False, content=message, model=model)


@runtime_checkable
class QueryAdapter(Protocol):
    """Protocol for routing LLM calls through custom backends.

    Open-source default: None (raw HTTP via OpenAI-compatible endpoint).
    ContextDNA IDE: injects priority_queue adapter for GPU scheduling.
    Any callable matching this signature works as an adapter.
    """

    def __call__(
        self,
        system: str,
        prompt: str,
        max_tokens: int,
        temperature: float,
        timeout_s: float,
    ) -> "LLMResponse": ...


class LLMProvider:
    """Unified LLM provider using the OpenAI-compatible chat completions API.

    Works with OpenAI, Ollama, local MLX servers, or any endpoint that
    implements the /v1/chat/completions interface.

    Optional query_adapter: when provided, all LLM calls route through the
    adapter instead of raw HTTP. This enables priority queue scheduling,
    rate limiting, or any custom routing without changing callers.
    """

    def __init__(
        self,
        config: SurgeonConfig,
        query_adapter: Optional[Callable[..., "LLMResponse"]] = None,
    ) -> None:
        self.endpoint: str = config.endpoint.rstrip("/")
        self.model: str = config.model
        self._api_key: Optional[str] = config.get_api_key()
        self._is_local: bool = config.provider in ("ollama", "mlx", "local")
        self._adapter = query_adapter

    def query(
        self,
        system: str,
        prompt: str,
        max_tokens: int = 2048,
        temperature: float = 0.7,
        timeout_s: float = 300.0,
    ) -> LLMResponse:
        """Send a chat completion request and return a structured response.

        POSTs to {endpoint}/chat/completions with the OpenAI-compatible
        messages format. Handles connection errors, HTTP errors, and
        unexpected exceptions gracefully.

        For local models, <think> reasoning blocks are stripped from the
        response so callers always get clean content.
        """
        if self._adapter is not None:
            return self._query_via_adapter(system, prompt, max_tokens, temperature, timeout_s)

        url = f"{self.endpoint}/chat/completions"
        headers: Dict[str, str] = {"Content-Type": "application/json"}
        if self._api_key:
            headers["Authorization"] = f"Bearer {self._api_key}"

        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": prompt},
            ],
            "max_tokens": max_tokens,
            "temperature": temperature,
        }

        t0 = time.monotonic()
        try:
            with httpx.Client(timeout=timeout_s) as client:
                resp = client.post(url, json=payload, headers=headers)
                resp.raise_for_status()
            latency_ms = int((time.monotonic() - t0) * 1000)

            data = resp.json()
            content = data["choices"][0]["message"]["content"]
            # Strip <think> reasoning blocks from local models (Qwen3, etc.)
            if self._is_local:
                content = strip_think_tags(content)

            # Extract token usage if available
            usage = data.get("usage", {})
            tokens_in = usage.get("prompt_tokens", 0)
            tokens_out = usage.get("completion_tokens", 0)
            cost = estimate_cost(self.model, tokens_in, tokens_out)

            return LLMResponse(
                ok=True,
                content=content,
                latency_ms=latency_ms,
                model=self.model,
                cost_usd=cost,
                tokens_in=tokens_in,
                tokens_out=tokens_out,
            )

        except httpx.ConnectError as exc:
            latency_ms = int((time.monotonic() - t0) * 1000)
            return LLMResponse(
                ok=False,
                content=f"Connection error: {exc}",
                latency_ms=latency_ms,
                model=self.model,
            )

        except httpx.HTTPStatusError as exc:
            latency_ms = int((time.monotonic() - t0) * 1000)
            return LLMResponse(
                ok=False,
                content=f"HTTP {exc.response.status_code}: {exc.response.text}",
                latency_ms=latency_ms,
                model=self.model,
            )

        except Exception as exc:
            latency_ms = int((time.monotonic() - t0) * 1000)
            return LLMResponse(
                ok=False,
                content=f"Unexpected error: {exc}",
                latency_ms=latency_ms,
                model=self.model,
            )

    def _query_via_adapter(
        self,
        system: str,
        prompt: str,
        max_tokens: int,
        temperature: float,
        timeout_s: float,
    ) -> LLMResponse:
        """Route query through the injected adapter."""
        t0 = time.monotonic()
        try:
            resp = self._adapter(system, prompt, max_tokens, temperature, timeout_s)
            if self._is_local and resp.ok:
                resp = LLMResponse(
                    ok=resp.ok,
                    content=strip_think_tags(resp.content),
                    latency_ms=resp.latency_ms or int((time.monotonic() - t0) * 1000),
                    model=resp.model or self.model,
                    cost_usd=resp.cost_usd,
                    tokens_in=resp.tokens_in,
                    tokens_out=resp.tokens_out,
                )
            return resp
        except Exception as exc:
            latency_ms = int((time.monotonic() - t0) * 1000)
            return LLMResponse(
                ok=False,
                content=f"Adapter error: {exc}",
                latency_ms=latency_ms,
                model=self.model,
            )

    def ping(self, timeout_s: float = 5.0) -> LLMResponse:
        """Quick health check -- asks the model to say 'operational'."""
        return self.query(
            system="You are a health check responder.",
            prompt="Say 'operational' in one word.",
            max_tokens=32,
            timeout_s=timeout_s,
        )


def create_provider(config: SurgeonConfig) -> LLMProvider:
    """Factory function to create an LLMProvider from a SurgeonConfig."""
    return LLMProvider(config)
