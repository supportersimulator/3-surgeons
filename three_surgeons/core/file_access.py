"""File access policy — HSIP-1PHASE 4-outcome model.

Validates file paths before reading. Fail-fast evaluation order
(cheapest rejections first):
  1. Empty / null byte → SILENT_REJECT
  2. Path.resolve() + is_relative_to → SILENT_REJECT if outside base
  3. Denylist (names, path parts, suffixes) → AUTO_DENY
  4. Existence → AUTO_DENY if not a file
  5. Binary detection (null in first 512B) → AUTO_DENY
  6. All clear → AUTO_ACCEPT
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import List, Optional

logger = logging.getLogger(__name__)

# ── Denylist ────────────────────────────────────────────────────────

_DENIED_NAMES: frozenset[str] = frozenset({
    ".env", ".env.local", ".env.production", ".env.staging",
    "credentials.json", "service-account.json",
    ".netrc", ".pgpass", ".my.cnf",
})

_DENIED_PATH_PARTS: frozenset[str] = frozenset({
    ".ssh", ".aws", ".gnupg", ".git",
})

_DENIED_SUFFIXES: frozenset[str] = frozenset({
    ".pem", ".key", ".p12", ".pfx", ".keystore",
})


# ── Outcome model ──────────────────────────────────────────────────


class AccessOutcome(Enum):
    """Four possible outcomes from a file access check."""

    AUTO_ACCEPT = "auto_accept"
    AUTO_DENY = "auto_deny"
    QUEUE_FOR_REVIEW = "queue_for_review"  # future: user prompt
    SILENT_REJECT = "silent_reject"


@dataclass(frozen=True)
class FileAccessResult:
    """Result of a file access policy check."""

    outcome: AccessOutcome
    reason: str
    canonical_path: Optional[str] = None


# ── Policy ──────────────────────────────────────────────────────────


class FileAccessPolicy:
    """Validates file paths against base directories and denylists.

    Args:
        base_dirs: Allowed root directories. Paths must resolve inside one.
    """

    def __init__(self, base_dirs: List[Path]) -> None:
        self._base_dirs: List[Path] = [Path(d).resolve() for d in base_dirs]

    def check(self, path: str) -> FileAccessResult:
        """Evaluate a file path. Returns outcome + reason."""

        # 1. Empty path / null byte
        if not path or "\x00" in path:
            return FileAccessResult(
                outcome=AccessOutcome.SILENT_REJECT,
                reason="invalid path",
            )

        # 2. Resolve and check containment
        try:
            resolved = Path(path).resolve()
        except (OSError, ValueError):
            return FileAccessResult(
                outcome=AccessOutcome.SILENT_REJECT,
                reason="invalid path",
            )

        if not any(self._is_within(resolved, base) for base in self._base_dirs):
            return FileAccessResult(
                outcome=AccessOutcome.SILENT_REJECT,
                reason="invalid path",
            )

        canonical = str(resolved)

        # 3. Denylist — names
        if resolved.name in _DENIED_NAMES:
            logger.warning("File access denied (sensitive name): %s", canonical)
            return FileAccessResult(
                outcome=AccessOutcome.AUTO_DENY,
                reason=f"Denylist: sensitive file name '{resolved.name}'",
                canonical_path=canonical,
            )

        # 3. Denylist — path parts
        for part in resolved.parts:
            if part in _DENIED_PATH_PARTS:
                logger.warning("File access denied (sensitive path part): %s", canonical)
                return FileAccessResult(
                    outcome=AccessOutcome.AUTO_DENY,
                    reason=f"Denylist: sensitive path component '{part}'",
                    canonical_path=canonical,
                )

        # 3. Denylist — suffixes
        if resolved.suffix in _DENIED_SUFFIXES:
            logger.warning("File access denied (sensitive suffix): %s", canonical)
            return FileAccessResult(
                outcome=AccessOutcome.AUTO_DENY,
                reason=f"Denylist: sensitive file suffix '{resolved.suffix}'",
                canonical_path=canonical,
            )

        # 4. Existence check
        if not resolved.is_file():
            return FileAccessResult(
                outcome=AccessOutcome.AUTO_DENY,
                reason="File does not exist or is not a regular file",
                canonical_path=canonical,
            )

        # 5. Binary detection (null bytes in first 512 bytes)
        try:
            with open(resolved, "rb") as f:
                chunk = f.read(512)
            if b"\x00" in chunk:
                logger.warning("File access denied (binary file): %s", canonical)
                return FileAccessResult(
                    outcome=AccessOutcome.AUTO_DENY,
                    reason="Binary file detected (null bytes in first 512 bytes)",
                    canonical_path=canonical,
                )
        except OSError:
            return FileAccessResult(
                outcome=AccessOutcome.AUTO_DENY,
                reason="Cannot read file for binary check",
                canonical_path=canonical,
            )

        # 6. All clear
        return FileAccessResult(
            outcome=AccessOutcome.AUTO_ACCEPT,
            reason="File is safe to read",
            canonical_path=canonical,
        )

    @staticmethod
    def _is_within(path: Path, base: Path) -> bool:
        """Check if resolved path is within base directory."""
        try:
            return path.is_relative_to(base)
        except TypeError:
            # Fallback for Python < 3.9
            try:
                path.relative_to(base)
                return True
            except ValueError:
                return False


# ── Chunked reading ────────────────────────────────────────────────


def read_file_chunked(
    path: str,
    chunk_size: int = 32768,
    overlap: int = 2048,
) -> List[str]:
    """Read a file in chunks with overlap for LLM context continuity.

    Args:
        path: Canonical file path (already validated by policy).
        chunk_size: Max chars per chunk (default 32KB).
        overlap: Chars of overlap between consecutive chunks (default 2KB).

    Returns:
        List of string chunks. Single-element list if file fits in one chunk.

    Raises:
        ValueError: If overlap >= chunk_size (would cause infinite loop).
    """
    if overlap >= chunk_size:
        raise ValueError(f"overlap ({overlap}) must be < chunk_size ({chunk_size})")

    with open(path, "r") as f:
        content = f.read()

    if len(content) <= chunk_size:
        return [content]

    chunks: List[str] = []
    start = 0
    while start < len(content):
        end = start + chunk_size
        chunks.append(content[start:end])
        start = end - overlap  # Step back by overlap amount
    return chunks


def read_files_with_budget(
    paths: List[str],
    policy: FileAccessPolicy,
    total_budget: int = 50000,
    chunk_size: int = 32768,
    overlap: int = 2048,
) -> dict[str, str]:
    """Read multiple files within a total character budget.

    Fair distribution: each file gets budget/N chars, leftover redistributed.
    Files that fail policy checks are silently excluded.

    Returns:
        Dict mapping file path to content (possibly truncated).
    """
    if total_budget <= 0:
        return {}

    # Filter to allowed files
    allowed: List[str] = []
    for p in paths:
        check_result = policy.check(p)
        if check_result.outcome == AccessOutcome.AUTO_ACCEPT:
            allowed.append(check_result.canonical_path)

    if not allowed:
        return {}

    per_file = total_budget // len(allowed)
    result: dict[str, str] = {}
    remaining = total_budget

    for file_path in allowed:
        if remaining <= 0:
            break
        budget = min(per_file, remaining)
        chunks = read_file_chunked(file_path, chunk_size=chunk_size, overlap=overlap)
        # Take chunks until budget exhausted
        content_parts: List[str] = []
        chars_used = 0
        for chunk in chunks:
            if chars_used + len(chunk) > budget:
                # Take partial chunk up to budget
                content_parts.append(chunk[:budget - chars_used])
                chars_used = budget
                break
            content_parts.append(chunk)
            chars_used += len(chunk)
        result[file_path] = sanitize_for_llm("".join(content_parts))
        remaining -= chars_used

    return result


# ── Prompt injection defense ───────────────────────────────────────

# Prompt injection patterns — standalone directives, NOT legitimate code
_INJECTION_PATTERNS = [
    re.compile(r"IGNORE\s+ALL\s+PREVIOUS\s+INSTRUCTIONS", re.IGNORECASE),
    re.compile(r"YOU\s+ARE\s+NOW\b", re.IGNORECASE),
    re.compile(r"DISREGARD\s+(ALL\s+)?(PRIOR|PREVIOUS|ABOVE)", re.IGNORECASE),
    re.compile(r"NEW\s+INSTRUCTIONS?\s*:", re.IGNORECASE),
    re.compile(r"OVERRIDE\s+SYSTEM\s+PROMPT", re.IGNORECASE),
]

# LLM role/control markers — never legitimate in source files
_ROLE_MARKERS = [
    "<|system|>", "</|system|>", "<|assistant|>", "</|assistant|>",
    "<|user|>", "</|user|>", "[INST]", "[/INST]",
    "<<SYS>>", "<</SYS>>", "<|im_start|>", "<|im_end|>",
]


def sanitize_for_llm(content: str) -> str:
    """Remove prompt injection attempts from file content.

    Strategy: strip known injection patterns and LLM role markers.
    Preserves legitimate code that happens to contain similar words
    in comments/strings by only matching standalone directive patterns.
    """
    result = content
    for pattern in _INJECTION_PATTERNS:
        result = pattern.sub("[CONTENT_FILTERED]", result)
    for marker in _ROLE_MARKERS:
        result = result.replace(marker, "[CONTENT_FILTERED]")
    return result


def wrap_file_content(filename: str, content: str) -> str:
    """Wrap file content with boundary markers to prevent context bleed."""
    safe_name = sanitize_for_llm(filename.replace("\n", "").replace("\r", ""))
    return f"─── FILE: {safe_name} ───\n{content}\n─── END FILE ───"
