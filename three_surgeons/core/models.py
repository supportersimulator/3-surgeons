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
# Generalized CoT-wrapper detection — covers <think>, <thinking>, <reasoning>
# variants emitted by Qwen3, DeepSeek-R1 distill, future thinking models.
_COT_TAG_RE = re.compile(r"<(think|thinking|reasoning)>.*?</\1>\s*", re.DOTALL | re.IGNORECASE)
_COT_UNCLOSED_RE = re.compile(r"<(think|thinking|reasoning)>.*", re.DOTALL | re.IGNORECASE)
# Reasoning models that need bigger max_tokens budget for CoT overhead.
# Match by name pattern so future models auto-qualify without code changes.
_REASONING_MODEL_RE = re.compile(
    r"(reasoner|-r1\b|^o1|^o3|^o4|thinking|qwq)",
    re.IGNORECASE,
)
# Providers verified to accept OpenAI-style response_format={"type":"json_object"}.
# Empirical: OpenAI (native), DeepSeek (docs confirm), Groq (OpenAI-compat docs).
# Excluded: Mistral (partial model support), xAI (unverified) — would 400 on
# unsupported endpoints. Add only after verification.
_JSON_MODE_PROVIDERS = frozenset({"openai", "deepseek", "groq"})


def strip_think_tags(text: str) -> str:
    """Remove CoT/<think>-style reasoning wrappers from LLM output.

    Generalized to match `<think>`, `<thinking>`, `<reasoning>` (any case).
    Handles closed AND unclosed tags (budget exhausted mid-thought).
    Provider-agnostic: works for Qwen3, DeepSeek-R1 distill, future models.
    """
    if "<think" not in text.lower() and "<reasoning" not in text.lower():
        return text
    result = _COT_TAG_RE.sub("", text)
    result = _COT_UNCLOSED_RE.sub("", result)
    return result.strip()


def is_reasoning_model(model: str) -> bool:
    """True if model name matches a reasoning/CoT family (needs larger budget)."""
    return bool(_REASONING_MODEL_RE.search(model or ""))


def reasoning_max_tokens(model: str, requested: int) -> int:
    """Auto-bump max_tokens for reasoning models — CoT eats budget.

    Reasoning models often emit hundreds of CoT tokens before the final
    answer. With the requested budget unmodified, the final answer gets
    truncated mid-string (breaking strict JSON parsing). Bump 4× capped
    at 8192 to leave headroom without exploding cost on regular calls.

    Logs once at INFO when bump fires so the budget side-effect is
    observable to operators tracking daily_external_usd cap.
    """
    if is_reasoning_model(model):
        bumped = min(max(requested * 4, 2048), 8192)
        if bumped != requested:
            logger.info(
                "reasoning_max_tokens: model=%s bumped %d→%d (CoT budget headroom)",
                model, requested, bumped,
            )
        return bumped
    return requested


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
    """Structured response from an LLM provider call.

    `reasoning_content` is preserved separately from `content` so that
    multi-turn callers can re-inject CoT into subsequent assistant turns.

    `content_blocks` preserves the raw typed-block list when the provider
    returns one (Anthropic native, future protocols). Tool-using agents
    MUST inspect this to detect `tool_use` blocks — extracting only `text`
    into `content` would silently drop tool invocations.

    `finish_reason` surfaces why the model stopped (`stop`, `length`,
    `content_filter`, `tool_use`, etc.). Callers can detect non-`stop`
    cases without re-parsing the full API response.
    """

    ok: bool
    content: str
    latency_ms: int = 0
    model: str = ""
    cost_usd: float = 0.0
    tokens_in: int = 0
    tokens_out: int = 0
    reasoning_content: str = ""
    content_blocks: Optional[List[Dict]] = None
    finish_reason: str = ""

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
        self._provider: str = config.provider
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
        json_mode: bool = False,
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
                json_mode=json_mode, provider=self._provider,
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
                json_mode=json_mode, provider=fb_config.provider,
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
        json_mode: bool = False,
        provider: str = "",
    ) -> LLMResponse:
        """Execute a single HTTP request to an OpenAI-compatible endpoint.

        CoT-invariant content extraction:
        - Auto-bumps max_tokens for reasoning models (CoT eats budget)
        - Opt-in JSON mode via response_format (provider-aware)
        - Drops `reasoning_content` field, keeps `content` (DeepSeek-reasoner,
          o1-style, future thinking models)
        - Strips inline <think>/<thinking>/<reasoning> tags universally
        """
        url = f"{endpoint}/chat/completions"
        headers: Dict[str, str] = {"Content-Type": "application/json"}
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"

        # Layer 3: bump max_tokens for reasoning families
        effective_max = reasoning_max_tokens(model, max_tokens)

        payload: Dict = {
            "model": model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": prompt},
            ],
            "max_tokens": effective_max,
            "temperature": temperature,
        }

        # Layer 2: opt-in JSON mode where supported (eliminates prose wrapping)
        if json_mode and provider in _JSON_MODE_PROVIDERS:
            payload["response_format"] = {"type": "json_object"}

        t0 = time.monotonic()
        try:
            with httpx.Client(timeout=timeout_s) as client:
                resp = client.post(url, json=payload, headers=headers)
                resp.raise_for_status()
            latency_ms = int((time.monotonic() - t0) * 1000)

            data = resp.json()
            choice = data["choices"][0]
            finish_reason = str(choice.get("finish_reason") or "")
            # Layer 1: provider-aware extraction. Reasoning models split CoT
            # into a separate `reasoning_content` field — preserve it on the
            # response (multi-turn callers can re-inject) but use `content`
            # for the primary answer string.
            msg = choice["message"]
            raw_content = msg.get("content") or ""
            # Some providers (Anthropic native, future ones) return content as
            # a list of typed blocks: [{"type": "text", "text": "..."},
            # {"type": "thinking", "thinking": "..."}]. Concatenate text
            # blocks; route thinking blocks into reasoning_content.
            content_blocks: Optional[List[Dict]] = None
            if isinstance(raw_content, list):
                content_blocks = [b for b in raw_content if isinstance(b, dict)]
                text_parts: List[str] = []
                thinking_parts: List[str] = []
                for block in content_blocks:
                    btype = block.get("type", "")
                    if btype in ("text", "output_text"):
                        text_parts.append(str(block.get("text", "")))
                    elif btype in ("thinking", "reasoning"):
                        thinking_parts.append(str(block.get(btype, "") or block.get("text", "")))
                    # NOTE: tool_use, tool_result, image, etc. blocks are
                    # preserved on `content_blocks` for callers — NOT silently
                    # dropped. Tool-using agents inspect content_blocks
                    # directly to detect tool invocations.
                content = "".join(text_parts)
                inline_reasoning = "\n".join(p for p in thinking_parts if p)
            else:
                content = str(raw_content)
                inline_reasoning = ""
            reasoning_content = (
                str(msg.get("reasoning_content") or "") or inline_reasoning
            )
            # Defensive: if `content` is empty but reasoning_content present,
            # use last paragraph of reasoning as a fallback (rare; truncation).
            if not content and reasoning_content:
                content = (
                    reasoning_content.split("\n\n")[-1]
                    if "\n\n" in reasoning_content
                    else reasoning_content
                )
            # Universal CoT-tag strip (all providers, not just is_local) —
            # some hosted models inline <think> too.
            content = strip_think_tags(content)

            usage = data.get("usage", {})
            tokens_in = usage.get("prompt_tokens", 0)
            tokens_out = usage.get("completion_tokens", 0)
            cost = estimate_cost(model, tokens_in, tokens_out)

            # ZSF: log non-stop finish reasons so safety-filter / length /
            # tool_use truncation is observable. Don't auto-retry — the
            # caller decides (a length-truncation might want a bump, but a
            # content_filter never will).
            if finish_reason and finish_reason not in ("stop", "end_turn"):
                logger.warning(
                    "LLM finished with non-stop reason: %s (model=%s, content_len=%d)",
                    finish_reason, model, len(content),
                )
            return LLMResponse(
                ok=True,
                content=content,
                latency_ms=latency_ms,
                model=model,
                cost_usd=cost,
                tokens_in=tokens_in,
                tokens_out=tokens_out,
                reasoning_content=reasoning_content,
                content_blocks=content_blocks,
                finish_reason=finish_reason,
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
        """Quick health check -- asks the model to say 'operational'."""
        return self.query(
            system="You are a health check responder.",
            prompt="Say 'operational' in one word.",
            max_tokens=32,
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
