"""Tests for the GPU lock / priority queue system."""
from __future__ import annotations

import pytest

from three_surgeons.core.priority_queue import (
    Priority,
    GPULock,
    GenerationProfiles,
    extract_thinking,
)


class TestPriority:
    """Test priority enum ordering."""

    def test_ordering(self) -> None:
        """Lower numeric value = higher priority. USER_FACING < OPERATIONAL < EXTERNAL < BACKGROUND."""
        assert Priority.USER_FACING < Priority.OPERATIONAL
        assert Priority.OPERATIONAL < Priority.EXTERNAL
        assert Priority.EXTERNAL < Priority.BACKGROUND


class TestGPULock:
    """Test file-lock based GPU lock."""

    def test_acquire_release(self, tmp_path) -> None:
        """Acquire a lock, then release it successfully."""
        lock = GPULock(lock_dir=tmp_path)
        assert lock.acquire(timeout=1.0) is True
        lock.release()

    def test_double_acquire_fails(self, tmp_path) -> None:
        """Second lock on the same dir fails while first is held."""
        lock = GPULock(lock_dir=tmp_path)
        assert lock.acquire(timeout=1.0) is True
        lock2 = GPULock(lock_dir=tmp_path)
        assert lock2.acquire(timeout=0.5) is False
        lock.release()

    def test_stale_lock_stolen(self, tmp_path) -> None:
        """Lock file with a dead PID is treated as stale and stolen."""
        lock_file = tmp_path / "gpu.lock"
        lock_file.write_text("999999")  # Dead PID
        lock = GPULock(lock_dir=tmp_path)
        assert lock.acquire(timeout=1.0) is True
        lock.release()

    def test_context_manager(self, tmp_path) -> None:
        """GPULock can be used as a context manager."""
        lock = GPULock(lock_dir=tmp_path)
        with lock:
            # Lock should be held inside context
            lock2 = GPULock(lock_dir=tmp_path)
            assert lock2.acquire(timeout=0.2) is False
        # Lock should be released after context exits
        lock3 = GPULock(lock_dir=tmp_path)
        assert lock3.acquire(timeout=0.5) is True
        lock3.release()

    def test_release_without_acquire_is_safe(self, tmp_path) -> None:
        """Calling release without acquire does not raise."""
        lock = GPULock(lock_dir=tmp_path)
        lock.release()  # Should not raise


class TestGenerationProfiles:
    """Test named token budget profiles."""

    def test_classify_profile(self) -> None:
        """Classify profile: low tokens, low temperature."""
        params = GenerationProfiles.get("classify")
        assert params["max_tokens"] == 64
        assert params["temperature"] == 0.2

    def test_deep_profile(self) -> None:
        """Deep profile: high tokens for detailed generation."""
        params = GenerationProfiles.get("deep")
        assert params["max_tokens"] == 2048

    def test_unknown_falls_back(self) -> None:
        """Unknown profile name falls back to extract defaults."""
        params = GenerationProfiles.get("nonexistent")
        assert "max_tokens" in params

    def test_all_profiles_have_required_keys(self) -> None:
        """Every named profile must have max_tokens and temperature."""
        all_profiles = (
            "classify", "extract", "extract_deep", "voice",
            "deep", "s2_professor", "s8_synaptic",
            "coding", "explore", "reasoning", "summarize",
            "s2_professor_brief", "synaptic_chat", "post_analysis",
        )
        for name in all_profiles:
            params = GenerationProfiles.get(name)
            assert "max_tokens" in params, f"{name} missing max_tokens"
            assert "temperature" in params, f"{name} missing temperature"

    def test_coding_profile(self) -> None:
        params = GenerationProfiles.get("coding")
        assert params["max_tokens"] == 1024
        assert params["temperature"] == 0.4

    def test_summarize_profile(self) -> None:
        params = GenerationProfiles.get("summarize")
        assert params["max_tokens"] == 512
        assert params["temperature"] == 0.3

    def test_post_analysis_profile(self) -> None:
        params = GenerationProfiles.get("post_analysis")
        assert params["max_tokens"] == 1500

    def test_profile_count(self) -> None:
        """Should have at least 14 profiles."""
        assert len(GenerationProfiles._PROFILES) >= 14

    def test_extract_profile(self) -> None:
        """Extract profile: mid-range tokens."""
        params = GenerationProfiles.get("extract")
        assert params["max_tokens"] == 768
        assert params["temperature"] == 0.3

    def test_voice_profile(self) -> None:
        """Voice profile: 256 tokens, moderate temperature."""
        params = GenerationProfiles.get("voice")
        assert params["max_tokens"] == 256
        assert params["temperature"] == 0.5


class TestExtractThinking:
    """Test <think> tag extraction from LLM responses."""

    def test_closed_think_tags(self) -> None:
        """Properly closed <think>...</think> tags are extracted."""
        text = "<think>reasoning here</think>final answer"
        response, thinking = extract_thinking(text)
        assert response == "final answer"
        assert thinking == "reasoning here"

    def test_no_think_tags(self) -> None:
        """No think tags: response is the full text, thinking is None."""
        response, thinking = extract_thinking("just an answer")
        assert response == "just an answer"
        assert thinking is None

    def test_unclosed_think(self) -> None:
        """Unclosed <think> tag: everything after <think> is thinking."""
        text = "<think>partial reasoning"
        response, thinking = extract_thinking(text)
        assert thinking == "partial reasoning"

    def test_whitespace_stripping(self) -> None:
        """Both response and thinking should be stripped of surrounding whitespace."""
        text = "<think>  reasoning with spaces  </think>  answer with spaces  "
        response, thinking = extract_thinking(text)
        assert response == "answer with spaces"
        assert thinking == "reasoning with spaces"

    def test_empty_think_tags(self) -> None:
        """Empty think tags produce empty thinking string."""
        text = "<think></think>the answer"
        response, thinking = extract_thinking(text)
        assert response == "the answer"
        assert thinking == ""


class TestGPULockedAdapterContentExtraction:
    """Adapter must tolerate Qwen3 reasoning-only responses (HH4 root cause).

    The GPU-locked adapter previously did
    ``data["choices"][0]["message"]["content"]`` which raises ``KeyError``
    when ``mlx_lm.server`` returns a Qwen3 thinking-mode response with
    ``message.reasoning`` instead of ``message.content``. This breaks
    Neurologist consensus. These tests pin the fix.
    """

    def _make_adapter(self, monkeypatch, payload: dict, tmp_path):
        """Build a make_gpu_locked_adapter wired to a fake httpx.Client."""
        from three_surgeons.core import priority_queue as pq
        from three_surgeons.core.config import SurgeonConfig

        class _FakeResp:
            def raise_for_status(self) -> None:
                return None

            def json(self) -> dict:
                return payload

        class _FakeClient:
            def __init__(self, *a, **kw) -> None:
                pass

            def __enter__(self):
                return self

            def __exit__(self, *exc) -> None:
                return None

            def post(self, url, json=None, headers=None):
                return _FakeResp()

        # Replace httpx in the priority_queue module's deferred import path
        import httpx as real_httpx
        monkeypatch.setattr(real_httpx, "Client", _FakeClient)

        # Reset ZSF counters so each test sees a fresh slate
        pq._reset_gpu_adapter_metrics()

        cfg = SurgeonConfig(
            provider="mlx",
            endpoint="http://127.0.0.1:5044/v1",
            model="qwen3-4b",
            api_key_env="",
            role="neurologist",
        )
        adapter = pq.make_gpu_locked_adapter(cfg, lock_dir=tmp_path)
        return adapter, pq

    def test_legacy_content_only_response(self, monkeypatch, tmp_path) -> None:
        """OpenAI/DeepSeek shape with ``content`` key still works."""
        payload = {
            "choices": [{"message": {"role": "assistant", "content": "hello world"}}],
            "usage": {"prompt_tokens": 5, "completion_tokens": 2},
        }
        adapter, pq = self._make_adapter(monkeypatch, payload, tmp_path)
        resp = adapter("sys", "prompt", 64, 0.2, 5.0)
        assert resp.ok is True
        assert resp.content == "hello world"
        # Legacy path -- no reasoning-only event, no empty event
        metrics = pq.gpu_adapter_metrics()
        assert metrics["empty_content"] == 0
        assert metrics["reasoning_only_responses"] == 0

    def test_qwen3_reasoning_only_response(self, monkeypatch, tmp_path) -> None:
        """Qwen3 thinking-mode: ``reasoning`` present, ``content`` absent.

        Pre-fix this raised ``KeyError: 'content'`` and broke 3-surgeon
        consensus (HH4 audit). Post-fix, content surfaces wrapped in
        ``<think>...</think>`` so ``strip_think_tags`` can clean it.
        """
        payload = {
            "choices": [
                {"message": {"role": "assistant", "reasoning": "I am thinking..."}}
            ],
            "usage": {"prompt_tokens": 5, "completion_tokens": 4},
        }
        adapter, pq = self._make_adapter(monkeypatch, payload, tmp_path)
        resp = adapter("sys", "prompt", 64, 0.2, 5.0)
        assert resp.ok is True
        # Reasoning is surfaced (think-tag wrapped) so neurologist stays usable
        assert resp.content == "<think>I am thinking...</think>"
        metrics = pq.gpu_adapter_metrics()
        assert metrics["reasoning_only_responses"] == 1
        assert metrics["empty_content"] == 0

    def test_both_content_and_reasoning_prefers_content(
        self, monkeypatch, tmp_path
    ) -> None:
        """When both fields are present, ``content`` wins (backwards-compat)."""
        payload = {
            "choices": [
                {
                    "message": {
                        "role": "assistant",
                        "content": "final answer",
                        "reasoning": "scratch work",
                    }
                }
            ],
            "usage": {},
        }
        adapter, pq = self._make_adapter(monkeypatch, payload, tmp_path)
        resp = adapter("sys", "prompt", 64, 0.2, 5.0)
        assert resp.ok is True
        assert resp.content == "final answer"
        metrics = pq.gpu_adapter_metrics()
        assert metrics["reasoning_only_responses"] == 0

    def test_neither_content_nor_reasoning_returns_empty_and_bumps_counter(
        self, monkeypatch, tmp_path
    ) -> None:
        """Pathological response: empty fallback + ZSF counter increment.

        ZSF: silent empty content is forbidden; the counter MUST advance so
        ops/health channels can see the failure mode.
        """
        payload = {
            "choices": [{"message": {"role": "assistant"}}],
            "usage": {},
        }
        adapter, pq = self._make_adapter(monkeypatch, payload, tmp_path)
        resp = adapter("sys", "prompt", 64, 0.2, 5.0)
        # ok=True because HTTP succeeded; content is empty by design
        assert resp.ok is True
        assert resp.content == ""
        metrics = pq.gpu_adapter_metrics()
        assert metrics["empty_content"] == 1
