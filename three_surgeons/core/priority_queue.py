"""GPU lock and priority queue system for the 3-Surgeons plugin.

Portable extraction from ContextDNA's llm_priority_queue.py.
File-lock based GPU lock (no Redis required), priority-aware yielding,
generation profiles, and <think> tag extraction.
"""
from __future__ import annotations

import enum
import json as _json
import os
import random
import re
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional, Protocol, Tuple, runtime_checkable

# Qwen3 native thinking mode: responses may contain <think>...</think> blocks
_THINK_PATTERN = re.compile(r"<think>(.*?)</think>", re.DOTALL)


@runtime_checkable
class LockBackend(Protocol):
    """Protocol for GPU/resource lock backends.

    Implementations: FileLockBackend (Phase 1), RedisLockBackend (Phase 2).
    """

    def acquire(self, priority: int = 4, caller: str = "", timeout: float = 5.0) -> bool:
        """Acquire the lock. Returns True if acquired within timeout."""
        ...

    def release(self, caller: str = "") -> None:
        """Release the lock."""
        ...

    def is_locked(self) -> Tuple[bool, Optional[str]]:
        """Check lock status. Returns (is_locked, holder_info)."""
        ...

    def health_check(self) -> bool:
        """Check if the lock backend is healthy."""
        ...

    def renew(self, caller: str, extend_s: float) -> bool:
        """Extend the lock TTL. Returns True if renewed."""
        ...


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

    Intra-process serialisation: a per-directory threading.Lock ensures
    that concurrent callers within the same process (e.g. parallel MCP
    tool calls) queue up rather than all racing on the same file lock
    (which is per-process on macOS/Linux and would silently succeed for
    the same PID).

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

    # Per-directory threading locks for intra-process serialisation.
    # Key: resolved lock_dir string → threading.Lock
    _thread_locks: dict[str, threading.Lock] = {}
    _thread_locks_guard = threading.Lock()

    def __init__(self, lock_dir: Path) -> None:
        self._lock_dir = Path(lock_dir)
        self._lock_path = self._lock_dir / self.LOCK_FILENAME
        self._held = False
        self._caller: Optional[str] = None
        self._thread_lock = self._get_thread_lock(str(self._lock_dir))

    @classmethod
    def _get_thread_lock(cls, key: str) -> threading.Lock:
        with cls._thread_locks_guard:
            if key not in cls._thread_locks:
                cls._thread_locks[key] = threading.Lock()
            return cls._thread_locks[key]

    def acquire(self, timeout: float = 5.0) -> bool:
        """Try to acquire the GPU lock within *timeout* seconds.

        First acquires an intra-process threading lock (serialises callers
        within the same process), then the file-based lock (serialises
        across processes).

        Polls with exponential backoff (100ms initial, 2s cap).
        Steals locks held by dead PIDs.

        Returns True if acquired, False if timed out.
        """
        # Intra-process gate: block until our turn within this process
        if not self._thread_lock.acquire(timeout=timeout):
            return False

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
                self._thread_lock.release()
                return False

            # Sleep with backoff, but don't overshoot the deadline
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                self._thread_lock.release()
                return False
            time.sleep(min(backoff, remaining))
            backoff = min(backoff * 1.5, 2.0)

    def release(self) -> None:
        """Release the GPU lock by removing the lock file and threading lock.

        Safe to call even if the lock is not held (no-op).
        """
        if not self._held:
            return
        try:
            self._lock_path.unlink(missing_ok=True)
        except OSError:
            pass
        self._held = False
        try:
            self._thread_lock.release()
        except RuntimeError:
            pass  # already released

    def _try_lock(self) -> bool:
        """Attempt to atomically create the lock file with our PID.

        Uses O_CREAT | O_EXCL for atomic creation (fails if file exists).
        Writes JSON metadata: pid, timestamp, caller for debuggability.
        """
        try:
            fd = os.open(
                str(self._lock_path),
                os.O_CREAT | os.O_EXCL | os.O_WRONLY,
                0o644,
            )
            metadata = _json.dumps({
                "pid": os.getpid(),
                "ts": datetime.now(timezone.utc).isoformat(),
                "caller": self._caller or "",
            })
            os.write(fd, metadata.encode())
            os.close(fd)
            return True
        except FileExistsError:
            return False
        except OSError:
            return False

    def _steal_stale(self) -> bool:
        """Check if the current lock holder is dead. If so, remove the lock file.

        Returns True if a stale lock was removed (caller should retry _try_lock).
        Parses JSON metadata or falls back to plain PID for backward compat.

        A4 2026-05-14: also reclaims self-orphaned locks (lock file claims our
        own PID but no live thread holds the intra-process threading.Lock and
        the file is older than _SELF_ORPHAN_GRACE_S). Caused by worker threads
        dying before their `finally: release()` ran.
        """
        try:
            content = self._lock_path.read_text().strip()
            if not content:
                self._lock_path.unlink(missing_ok=True)
                return True
            # Try JSON first (new format), fall back to plain PID
            try:
                data = _json.loads(content)
                pid = int(data["pid"])
            except (ValueError, KeyError, TypeError):
                pid = int(content)
            if not _is_pid_alive(pid):
                self._lock_path.unlink(missing_ok=True)
                return True
            # Self-orphan check: lock claims our PID but the thread that
            # acquired it is gone. Detect by testing whether the per-dir
            # threading.Lock is acquirable non-blocking; if yes, no live
            # thread is holding the in-process side of the GPULock pair,
            # so the file lock is orphaned. Grace period guards races.
            if pid == os.getpid():
                age = _self_orphan_lock_age_s(self._lock_path)
                if age is not None and age >= _SELF_ORPHAN_GRACE_S:
                    # We're already holding self._thread_lock at this point
                    # (acquire() acquired it before calling _steal_stale).
                    # That alone proves no OTHER thread in this process
                    # holds the lock — a dead thread holding it would have
                    # blocked our acquire above. So this self-orphan is
                    # safe to reclaim.
                    try:
                        self._lock_path.unlink(missing_ok=True)
                        _GPU_ADAPTER_METRICS["self_orphaned_lock_reclaimed"] += 1
                        return True
                    except OSError:
                        _GPU_ADAPTER_METRICS["stale_lock_reclaim_errors"] += 1
        except (OSError, ValueError):
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


class FileLockBackend:
    """Adapts GPULock to the LockBackend protocol.

    Wraps the existing file-based GPU lock for Phase 1 compatibility.
    """

    def __init__(self, lock_dir: Path) -> None:
        self._lock = GPULock(lock_dir=lock_dir)
        self._caller: Optional[str] = None

    def acquire(self, priority: int = 4, caller: str = "", timeout: float = 5.0) -> bool:
        self._lock._caller = caller
        result = self._lock.acquire(timeout=timeout)
        if result:
            self._caller = caller
        return result

    def release(self, caller: str = "") -> None:
        self._lock.release()
        self._caller = None

    def is_locked(self) -> Tuple[bool, Optional[str]]:
        lock_path = self._lock._lock_path
        if not lock_path.exists():
            return (False, None)
        try:
            content = lock_path.read_text().strip()
            try:
                data = _json.loads(content)
                info = f"pid:{data.get('pid')} caller:{data.get('caller', '')} since:{data.get('ts', '')}"
                return (True, info)
            except (ValueError, TypeError):
                return (True, f"pid:{content}")
        except OSError:
            return (True, None)

    def health_check(self) -> bool:
        return self._lock._lock_dir.exists()

    def renew(self, caller: str, extend_s: float) -> bool:
        # File locks don't have TTL — renew is a no-op success if held
        return self._lock._held


class RedisLockBackend:
    """Redis-based LockBackend using SETNX + TTL.

    PID stored in lock value for liveness check.
    Priority yielding via gpu_urgent flag.
    """

    DEFAULT_TTL = 300  # 5 minutes

    def __init__(
        self,
        client: Any = None,
        key_prefix: str = "3surgeons:gpu_lock",
        ttl: int = 300,
    ) -> None:
        self._client = client
        self._key = key_prefix
        self._urgent_key = f"{key_prefix}:urgent"
        self._ttl = ttl
        self._held = False
        self._caller: Optional[str] = None

    def acquire(self, priority: int = 4, caller: str = "", timeout: float = 5.0) -> bool:
        value = _json.dumps({"pid": os.getpid(), "caller": caller, "priority": priority})
        deadline = time.monotonic() + timeout
        backoff = 0.1

        while True:
            if self._client.set(self._key, value, nx=True, ex=self._ttl):
                self._held = True
                self._caller = caller
                if priority <= 2:
                    self._client.set(self._urgent_key, "1", ex=self._ttl)
                return True

            if time.monotonic() >= deadline:
                return False

            jitter = random.uniform(0, 0.4)
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return False
            time.sleep(min(backoff + jitter, remaining))
            backoff = min(backoff * 1.5, 2.0)

    def release(self, caller: str = "") -> None:
        if self._held:
            self._client.delete(self._key)
            self._client.delete(self._urgent_key)
            self._held = False
            self._caller = None

    def is_locked(self) -> Tuple[bool, Optional[str]]:
        value = self._client.get(self._key)
        if value is None:
            return (False, None)
        try:
            data = _json.loads(value) if isinstance(value, str) else _json.loads(value.decode())
            return (True, f"pid:{data.get('pid')} caller:{data.get('caller')}")
        except (ValueError, AttributeError):
            return (True, str(value))

    def health_check(self) -> bool:
        try:
            return self._client.ping()
        except Exception:
            return False

    def renew(self, caller: str, extend_s: float) -> bool:
        if not self._held:
            return False
        try:
            return bool(self._client.expire(self._key, max(1, int(extend_s))))
        except Exception:
            return False


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
        "coding": {"max_tokens": 1024, "temperature": 0.4},
        "explore": {"max_tokens": 1024, "temperature": 0.5},
        "reasoning": {"max_tokens": 1024, "temperature": 0.3},
        "summarize": {"max_tokens": 512, "temperature": 0.3},
        "s2_professor_brief": {"max_tokens": 700, "temperature": 0.4},
        "synaptic_chat": {"max_tokens": 1024, "temperature": 0.6},
        "post_analysis": {"max_tokens": 1500, "temperature": 0.5},
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


# ── Default lock directory ────────────────────────────────────────────

# Use /tmp so the lock file coordinates with ContextDNA's file-based
# fallback lock (/tmp/contextdna_gpu.lock).  The 3-surgeons lock lives
# alongside it — same directory, different filename — so both systems
# respect the same GPU serialisation boundary.
DEFAULT_LOCK_DIR = Path("/tmp/3surgeons")


# ── ZSF observability counters ────────────────────────────────────────
#
# These module-level counters surface adapter-level extraction issues so a
# Qwen3 reasoning-mode response with no usable text doesn't silently produce
# an empty string. Read via priority_queue.gpu_adapter_metrics().
_GPU_ADAPTER_METRICS: Dict[str, int] = {
    "empty_content": 0,            # _extract_content returned ""
    "reasoning_only_responses": 0, # response had reasoning but no content key
    "self_orphaned_lock_reclaimed": 0,  # A4 2026-05-14: stale lock by our own PID, no FD
    "stale_lock_reclaim_errors": 0,     # A4 2026-05-14: self-stale check failed (ZSF)
}


# ── Self-orphaned lock reclaim (A4 2026-05-14) ────────────────────────
#
# Root cause: a worker thread that called GPULock.acquire() can die before
# running its `finally: lock.release()` (e.g. asyncio task cancellation that
# kills the wrapping thread before its finally clause executes, or a fatal
# signal handled out-of-band). The lock file is left on disk with our own
# PID. _steal_stale only reclaims locks held by DEAD PIDs, so a long-lived
# daemon (fleet_nerve_nats) accumulates self-orphaned locks indefinitely.
#
# Fix: if the lock file claims our own PID, the lock has been on disk for
# longer than _SELF_ORPHAN_GRACE_S, AND no live thread currently holds the
# GPULock's intra-process threading.Lock for that lock_dir, the lock is a
# self-orphan and can be safely reclaimed.
#
# Grace period guards against the race where one thread just created the
# file in _try_lock and the cleaner thread sees it. 30s is plenty since a
# normal LLM call returns in <30s; if it's older than 30s and the thread
# lock isn't held, the original worker is gone.

_SELF_ORPHAN_GRACE_S = 30.0


def _self_orphan_lock_age_s(lock_path: Path) -> Optional[float]:
    """Return how long *lock_path* has existed on disk, in seconds.

    Returns None if the file is missing or stat fails.
    """
    try:
        st = lock_path.stat()
    except OSError:
        return None
    return max(0.0, time.time() - st.st_mtime)


def gpu_adapter_metrics() -> Dict[str, int]:
    """Return a snapshot of GPU-locked adapter ZSF counters."""
    return dict(_GPU_ADAPTER_METRICS)


def _reset_gpu_adapter_metrics() -> None:
    """Reset counters (test-only helper)."""
    for k in list(_GPU_ADAPTER_METRICS):
        _GPU_ADAPTER_METRICS[k] = 0


_DEFAULT_GPU_LOCK_TIMEOUT_S = 300.0  # was 90.0 — see I7/2026-05-14 root-cause notes


def _gpu_lock_timeout_from_env(default: float = _DEFAULT_GPU_LOCK_TIMEOUT_S) -> float:
    """Read GPU_LOCK_TIMEOUT_S env var, fallback to *default* on parse error.

    Bogus / empty / non-positive values fall through to the default so a
    misconfigured shell can't shrink the timeout to zero (ZSF).
    """
    raw = os.environ.get("GPU_LOCK_TIMEOUT_S", "")
    if not raw:
        return float(default)
    try:
        v = float(raw)
        if v <= 0:
            return float(default)
        return v
    except (TypeError, ValueError):
        return float(default)


def make_gpu_locked_adapter(
    config: "SurgeonConfig",
    lock_dir: Optional[Path] = None,
    lock_timeout: Optional[float] = None,
) -> "Callable":
    """Create a QueryAdapter-compatible callable that wraps HTTP calls with a GPU lock.

    The returned function matches the ``QueryAdapter`` protocol::

        def adapter(system, prompt, max_tokens, temperature, timeout_s) -> LLMResponse

    It acquires a file-based GPU lock before hitting the local LLM, preventing
    concurrent Metal operations that can crash macOS.  When the lock is held by
    another process (ContextDNA scheduler, webhook, etc.) the caller blocks with
    exponential backoff until the lock is free or *lock_timeout* expires.

    Only useful for local providers (mlx, ollama, vllm, lmstudio).  For remote
    providers the lock is unnecessary — pass ``query_adapter=None`` instead.

    *lock_timeout* defaults to ``GPU_LOCK_TIMEOUT_S`` env var (300s = 5 minutes).
    Root-cause fix (I7, 2026-05-14): 90s was too aggressive for sequential
    brainstorms — cold-start can hit 60s, plus queue wait extends it. Five
    minutes covers cold-start + 4-deep queue wait without false timeouts.
    """
    import httpx as _httpx  # deferred so import cost is only paid when used

    from three_surgeons.core.models import LLMResponse, _extract_content

    _lock_dir = lock_dir or DEFAULT_LOCK_DIR
    _lock_dir.mkdir(parents=True, exist_ok=True)
    _endpoint = config.endpoint.rstrip("/")
    _model = config.model
    _api_key = config.get_api_key()
    if lock_timeout is None:
        lock_timeout = _gpu_lock_timeout_from_env()

    def _adapter(
        system: str,
        prompt: str,
        max_tokens: int,
        temperature: float,
        timeout_s: float,
    ) -> "LLMResponse":
        lock = GPULock(lock_dir=_lock_dir)
        if not lock.acquire(timeout=lock_timeout):
            return LLMResponse(
                ok=False,
                content=f"GPU lock timeout after {lock_timeout}s — another process holds the lock",
                model=_model,
            )
        try:
            url = f"{_endpoint}/chat/completions"
            headers: Dict[str, str] = {"Content-Type": "application/json"}
            if _api_key:
                headers["Authorization"] = f"Bearer {_api_key}"

            payload = {
                "model": _model,
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": prompt},
                ],
                "max_tokens": max_tokens,
                "temperature": temperature,
            }

            t0 = time.monotonic()
            with _httpx.Client(timeout=timeout_s) as client:
                resp = client.post(url, json=payload, headers=headers)
                resp.raise_for_status()
            latency_ms = int((time.monotonic() - t0) * 1000)

            data = resp.json()
            # Robust extraction: handles OpenAI shape, Qwen3 reasoning-only
            # responses (mlx_lm.server emits message.reasoning when the model
            # finishes mid-thought with no message.content), and several other
            # local-server variants. Mirrors models._single_query so the
            # GPU-locked adapter never raises KeyError on a Qwen3 thinking
            # response (HH4 root cause). ZSF: empty extraction bumps a
            # counter so silent failures stay observable.
            content = _extract_content(data)
            if not content:
                _GPU_ADAPTER_METRICS["empty_content"] += 1
            else:
                # Sniff: did we recover from a reasoning-only response?
                try:
                    msg = data["choices"][0]["message"]
                    if isinstance(msg, dict) and not msg.get("content") and msg.get("reasoning"):
                        _GPU_ADAPTER_METRICS["reasoning_only_responses"] += 1
                except (KeyError, IndexError, TypeError):
                    pass
            usage = data.get("usage", {})

            return LLMResponse(
                ok=True,
                content=content,
                latency_ms=latency_ms,
                model=_model,
                tokens_in=usage.get("prompt_tokens", 0),
                tokens_out=usage.get("completion_tokens", 0),
            )
        except Exception as exc:
            return LLMResponse(
                ok=False,
                content=f"GPU-locked query failed: {exc}",
                model=_model,
            )
        finally:
            lock.release()

    return _adapter
