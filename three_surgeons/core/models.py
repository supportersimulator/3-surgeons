"""LLM provider abstraction with OpenAI-compatible interface.

All providers (OpenAI, Ollama, local MLX) use the same /v1/chat/completions
interface. This module provides a unified LLMProvider that handles construction,
querying, cost estimation, and error handling.
"""
from __future__ import annotations

import logging
import re
import time
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional, Protocol, Tuple, runtime_checkable

import httpx

from three_surgeons.core.config import SurgeonConfig

logger = logging.getLogger(__name__)

# Pricing per 1M tokens: (input_usd, output_usd)
_THINK_RE = re.compile(r"<think>.*?</think>\s*", re.DOTALL)
_THINK_UNCLOSED_RE = re.compile(r"<think>.*", re.DOTALL)


def _extract_content(data: dict) -> str:
    """Extract text content from an /v1/chat/completions response payload.

    Handles the standard OpenAI shape and the common variants emitted by
    local servers (MLX, llama.cpp, Ollama):
      - choices[0].message.content      -- OpenAI / DeepSeek / vLLM
      - choices[0].text                  -- legacy completions / some MLX builds
      - choices[0].delta.content         -- streamed-shape echoed as final
      - message.content                  -- single-choice non-array variants
      - content                          -- bare-content shorthand

    Returns an empty string when no recognised field is present rather than
    raising — callers compare ok=True with content for downstream behaviour
    and a missing payload should surface as ``FAIL -- empty content`` rather
    than ``KeyError: 'choices'``.
    """
    if not isinstance(data, dict):
        return ""
    choices = data.get("choices")
    if isinstance(choices, list) and choices:
        first = choices[0]
        if isinstance(first, dict):
            msg = first.get("message")
            if isinstance(msg, dict):
                value = msg.get("content")
                if isinstance(value, str) and value:
                    return value
                # MLX (mlx-lm.server >=0.31) emits Qwen3 reasoning into a
                # ``reasoning`` field instead of inlining <think>...</think>
                # in ``content``. When the model finishes mid-thought the
                # ``content`` field is missing or empty entirely; surface the
                # reasoning so health checks see *something* and downstream
                # strip_think_tags() can clean it up later.
                reasoning = msg.get("reasoning")
                if isinstance(reasoning, str) and reasoning:
                    if isinstance(value, str) and value:
                        return value
                    return f"<think>{reasoning}</think>"
                if isinstance(value, str):
                    return value
            value = first.get("text")
            if isinstance(value, str):
                return value
            delta = first.get("delta")
            if isinstance(delta, dict):
                value = delta.get("content")
                if isinstance(value, str):
                    return value
    msg = data.get("message")
    if isinstance(msg, dict):
        value = msg.get("content")
        if isinstance(value, str):
            return value
    value = data.get("content")
    if isinstance(value, str):
        return value
    return ""


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
    # Anthropic
    "claude-sonnet-4-20250514": (3.00, 15.00),
    "claude-haiku-4-5-20251001": (0.80, 4.00),
    # Google
    "gemini-2.5-pro": (1.25, 10.00),
    "gemini-2.5-flash": (0.15, 0.60),
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
    # Cohere
    "command-r-plus": (2.50, 10.00),
    "command-r": (0.15, 0.60),
    # Perplexity
    "sonar-pro": (3.00, 15.00),
    "sonar": (1.00, 1.00),
    # Together
    "meta-llama/Llama-3.3-70B-Instruct-Turbo": (0.88, 0.88),
    "meta-llama/Llama-3.1-8B-Instruct-Turbo": (0.18, 0.18),
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

    Features:
    - Automatic retry with configurable fallback providers
    - Budget enforcement (daily spend cap)
    - Optional query_adapter for custom routing (priority queues, etc.)
    """

    def __init__(
        self,
        config: SurgeonConfig,
        query_adapter: Optional[Callable[..., "LLMResponse"]] = None,
        fallbacks: Optional[List[SurgeonConfig]] = None,
        max_retries: int = 1,
        budget_tracker: Optional[Callable[[], float]] = None,
        budget_limit: float = 0.0,
    ) -> None:
        self.endpoint: str = config.endpoint.rstrip("/")
        self.model: str = config.model
        self._api_key: Optional[str] = config.get_api_key()
        self._is_local: bool = config.provider in ("ollama", "mlx", "local", "vllm", "lmstudio")
        self._adapter = query_adapter
        self._fallbacks: List[SurgeonConfig] = fallbacks or []
        self._max_retries: int = max_retries
        self._budget_tracker = budget_tracker
        self._budget_limit = budget_limit

    def query(
        self,
        system: str,
        prompt: str,
        max_tokens: int = 2048,
        temperature: float = 0.7,
        timeout_s: float = 300.0,
    ) -> LLMResponse:
        """Send a chat completion request with retry and fallback support.

        Tries the primary endpoint first. On failure, retries up to
        max_retries times, then falls through to each fallback provider
        in order. Returns the first successful response, or the last
        error if all attempts fail.

        Budget enforcement: if budget_tracker and budget_limit are set,
        checks daily spend before external calls. Over-budget calls
        return an error without making the request.
        """
        if self._adapter is not None:
            return self._query_via_adapter(system, prompt, max_tokens, temperature, timeout_s)

        # Budget check for non-local providers
        if not self._is_local and self._budget_limit > 0 and self._budget_tracker:
            spent = self._budget_tracker()
            if spent >= self._budget_limit:
                return LLMResponse.error(
                    f"Daily budget exhausted (${spent:.2f} / ${self._budget_limit:.2f}). "
                    "Skipping external call.",
                    model=self.model,
                )

        # Try primary endpoint with retries
        last_error: Optional[LLMResponse] = None
        for attempt in range(1 + self._max_retries):
            resp = self._single_query(
                self.endpoint, self.model, self._api_key, self._is_local,
                system, prompt, max_tokens, temperature, timeout_s,
            )
            if resp.ok:
                return resp
            last_error = resp
            if attempt < self._max_retries:
                logger.warning(
                    "Primary LLM failed (attempt %d/%d, model=%s): %s",
                    attempt + 1, 1 + self._max_retries, self.model, resp.content,
                )

        # Try fallback providers
        for fb_config in self._fallbacks:
            fb_is_local = fb_config.provider in ("ollama", "mlx", "local", "vllm", "lmstudio")
            fb_key = fb_config.get_api_key()
            fb_endpoint = fb_config.endpoint.rstrip("/")
            logger.info("Falling back to %s (%s)", fb_config.provider, fb_config.model)
            resp = self._single_query(
                fb_endpoint, fb_config.model, fb_key, fb_is_local,
                system, prompt, max_tokens, temperature, timeout_s,
            )
            if resp.ok:
                return resp
            last_error = resp

        return last_error or LLMResponse.error("All providers failed", model=self.model)

    @staticmethod
    def _single_query(
        endpoint: str,
        model: str,
        api_key: Optional[str],
        is_local: bool,
        system: str,
        prompt: str,
        max_tokens: int,
        temperature: float,
        timeout_s: float,
    ) -> LLMResponse:
        """Execute a single HTTP request to an OpenAI-compatible endpoint."""
        url = f"{endpoint}/chat/completions"
        headers: Dict[str, str] = {"Content-Type": "application/json"}
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"

        payload = {
            "model": model,
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
            content = _extract_content(data)
            if is_local:
                content = strip_think_tags(content)

            usage = data.get("usage", {})
            tokens_in = usage.get("prompt_tokens", 0)
            tokens_out = usage.get("completion_tokens", 0)
            cost = estimate_cost(model, tokens_in, tokens_out)

            return LLMResponse(
                ok=True,
                content=content,
                latency_ms=latency_ms,
                model=model,
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
                model=model,
            )

        except httpx.HTTPStatusError as exc:
            latency_ms = int((time.monotonic() - t0) * 1000)
            return LLMResponse(
                ok=False,
                content=f"HTTP {exc.response.status_code}: {exc.response.text}",
                latency_ms=latency_ms,
                model=model,
            )

        except Exception as exc:
            latency_ms = int((time.monotonic() - t0) * 1000)
            return LLMResponse(
                ok=False,
                content=f"Unexpected error: {exc}",
                latency_ms=latency_ms,
                model=model,
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
        """Quick health check -- asks the model to say 'operational'.

        Local reasoning models (Qwen3, DeepSeek-R1) burn many tokens inside
        <think> blocks before emitting any visible content, so ``max_tokens``
        is sized for them; remote chat models simply ignore the extra
        headroom and stop at their natural EOS. ``strip_think_tags`` removes
        the reasoning before callers see the response.
        """
        max_tokens = 256 if self._is_local else 32
        return self.query(
            system="You are a health check responder.",
            prompt="Say 'operational' in one word.",
            max_tokens=max_tokens,
            timeout_s=timeout_s,
        )


def create_provider(
    config: SurgeonConfig,
    query_adapter: Optional[Callable[..., "LLMResponse"]] = None,
    fallbacks: Optional[List[SurgeonConfig]] = None,
    budget_tracker: Optional[Callable[[], float]] = None,
    budget_limit: float = 0.0,
) -> LLMProvider:
    """Factory function to create an LLMProvider from a SurgeonConfig."""
    return LLMProvider(
        config,
        query_adapter=query_adapter,
        fallbacks=fallbacks,
        budget_tracker=budget_tracker,
        budget_limit=budget_limit,
    )
