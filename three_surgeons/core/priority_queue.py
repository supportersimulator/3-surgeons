"""GPU lock and priority queue system for the 3-Surgeons plugin.

Portable extraction from ContextDNA's llm_priority_queue.py.
File-lock based GPU lock (no Redis required), priority-aware yielding,
generation profiles, and <think> tag extraction.
"""
from __future__ import annotations

import enum
import os
import re
import time
from pathlib import Path
from typing import Dict, Optional, Tuple

# Qwen3 native thinking mode: responses may contain <think>...</think> blocks
_THINK_PATTERN = re.compile(r"<think>(.*?)</think>", re.DOTALL)


class Priority(enum.IntEnum):
    """LLM access priority levels. Lower number = higher priority."""

    USER_FACING = 1   # User's direct queries (was AARON in ContextDNA)
    OPERATIONAL = 2   # Operational/injection LLM calls (was ATLAS)
    EXTERNAL = 3      # External integrations
    BACKGROUND = 4    # Background tasks (mining, batch jobs)


class GPULock:
    """File-lock based GPU lock. No Redis required.

    Prevents concurrent GPU/Metal operations by acquiring an exclusive
    lock file. Supports stale lock detection (dead PID) and exponential
    backoff polling.

    Usage:
        lock = GPULock(lock_dir=Path("/tmp"))
        if lock.acquire(timeout=5.0):
            try:
                # do GPU work
            finally:
                lock.release()

    Or as a context manager:
        with GPULock(lock_dir=Path("/tmp")):
            # do GPU work
    """

    LOCK_FILENAME = "gpu.lock"

    def __init__(self, lock_dir: Path) -> None:
        self._lock_dir = Path(lock_dir)
        self._lock_path = self._lock_dir / self.LOCK_FILENAME
        self._held = False

    def acquire(self, timeout: float = 5.0) -> bool:
        """Try to acquire the GPU lock within *timeout* seconds.

        Polls with exponential backoff (100ms initial, 2s cap).
        Steals locks held by dead PIDs.

        Returns True if acquired, False if timed out.
        """
        deadline = time.monotonic() + timeout
        backoff = 0.1

        while True:
            # Try to create the lock file exclusively
            if self._try_lock():
                self._held = True
                return True

            # Check for stale lock (holder PID is dead)
            if self._steal_stale():
                if self._try_lock():
                    self._held = True
                    return True

            # Out of time?
            if time.monotonic() >= deadline:
                return False

            # Sleep with backoff, but don't overshoot the deadline
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return False
            time.sleep(min(backoff, remaining))
            backoff = min(backoff * 1.5, 2.0)

    def release(self) -> None:
        """Release the GPU lock by removing the lock file.

        Safe to call even if the lock is not held (no-op).
        """
        if not self._held:
            return
        try:
            self._lock_path.unlink(missing_ok=True)
        except OSError:
            pass
        self._held = False

    def _try_lock(self) -> bool:
        """Attempt to atomically create the lock file with our PID.

        Uses O_CREAT | O_EXCL for atomic creation (fails if file exists).
        """
        try:
            fd = os.open(
                str(self._lock_path),
                os.O_CREAT | os.O_EXCL | os.O_WRONLY,
                0o644,
            )
            os.write(fd, str(os.getpid()).encode())
            os.close(fd)
            return True
        except FileExistsError:
            return False
        except OSError:
            return False

    def _steal_stale(self) -> bool:
        """Check if the current lock holder is dead. If so, remove the lock file.

        Returns True if a stale lock was removed (caller should retry _try_lock).
        """
        try:
            pid_str = self._lock_path.read_text().strip()
            if not pid_str:
                # Empty lock file -- treat as stale
                self._lock_path.unlink(missing_ok=True)
                return True
            pid = int(pid_str)
            if not _is_pid_alive(pid):
                self._lock_path.unlink(missing_ok=True)
                return True
        except (OSError, ValueError):
            # Can't read or parse -- try to remove as stale
            try:
                self._lock_path.unlink(missing_ok=True)
                return True
            except OSError:
                pass
        return False

    def __enter__(self) -> GPULock:
        if not self.acquire():
            raise TimeoutError("Could not acquire GPU lock")
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self.release()


class GenerationProfiles:
    """Named token budget profiles for LLM generation.

    Each profile specifies max_tokens and temperature (at minimum).
    Unknown names fall back to the ``extract`` profile.
    """

    _PROFILES: Dict[str, Dict] = {
        "classify": {"max_tokens": 64, "temperature": 0.2},
        "extract": {"max_tokens": 768, "temperature": 0.3},
        "extract_deep": {"max_tokens": 1024, "temperature": 0.3},
        "voice": {"max_tokens": 256, "temperature": 0.5},
        "deep": {"max_tokens": 2048, "temperature": 0.7},
        "s2_professor": {"max_tokens": 700, "temperature": 0.4},
        "s8_synaptic": {"max_tokens": 1500, "temperature": 0.6},
    }

    _FALLBACK = "extract"

    @classmethod
    def get(cls, name: str) -> Dict:
        """Return generation parameters for *name*.

        Falls back to the ``extract`` profile for unknown names.
        Returns a **copy** so callers can mutate without affecting defaults.
        """
        profile = cls._PROFILES.get(name, cls._PROFILES[cls._FALLBACK])
        return dict(profile)


def extract_thinking(text: str) -> Tuple[str, Optional[str]]:
    """Extract ``<think>...</think>`` reasoning from an LLM response.

    Handles three cases:
    1. Properly closed ``<think>reasoning</think>answer`` -- returns (answer, reasoning).
    2. No think tags -- returns (text, None).
    3. Unclosed ``<think>reasoning`` (token budget exhausted) -- returns best-effort parse.

    Both response and thinking are stripped of surrounding whitespace.
    """
    if not text:
        return (text, None)

    # Case 1: Properly closed <think>...</think>
    match = _THINK_PATTERN.search(text)
    if match:
        thinking = match.group(1).strip()
        response = _THINK_PATTERN.sub("", text).strip()
        return (response, thinking)

    # Case 2: Unclosed <think> (token budget exhausted before </think>)
    if "<think>" in text:
        parts = text.split("<think>", 1)
        before = parts[0].strip()
        thinking = parts[1].strip() if len(parts) > 1 else ""
        # If nothing before <think>, the LLM went straight to thinking
        if not before and thinking:
            return (thinking, thinking)
        return (before if before else thinking, thinking)

    # Case 3: No think tags at all
    return (text, None)


def _is_pid_alive(pid: int) -> bool:
    """Check if a process with the given PID is still running.

    Uses ``os.kill(pid, 0)`` which checks existence without sending a signal.
    """
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False
