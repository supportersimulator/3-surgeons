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
        for name in ("classify", "extract", "extract_deep", "voice",
                     "deep", "s2_professor", "s8_synaptic"):
            params = GenerationProfiles.get(name)
            assert "max_tokens" in params, f"{name} missing max_tokens"
            assert "temperature" in params, f"{name} missing temperature"

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
