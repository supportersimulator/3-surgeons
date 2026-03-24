"""Secure configuration — 4-tier credential resolution with log sanitization."""
from __future__ import annotations

import getpass
import logging
import os
import re
import sys
from typing import Any, Dict, List, Optional, Protocol, runtime_checkable

logger = logging.getLogger(__name__)


# ── Vault Provider Protocol ──────────────────────────────────────────


@runtime_checkable
class VaultProvider(Protocol):
    def get_secret(self, key: str) -> Optional[str]: ...
    def is_available(self) -> bool: ...


# ── SanitizingFilter ─────────────────────────────────────────────────


class SanitizingFilter(logging.Filter):
    """Strip secrets from log output. Applied to adapter loggers."""

    PATTERNS: List[re.Pattern] = [
        re.compile(r"sk-[a-zA-Z0-9]{20,}"),
        re.compile(r"key_[a-zA-Z0-9]+"),
        re.compile(r"(?i)bearer\s+\S+"),
        re.compile(r"(?i)token[=:]\s*\S+"),
    ]

    def filter(self, record: logging.LogRecord) -> bool:
        record.msg = self._sanitize(record.msg)
        if record.args:
            if isinstance(record.args, dict):
                record.args = {
                    k: self._sanitize(str(v)) for k, v in record.args.items()
                }
            elif isinstance(record.args, tuple):
                record.args = tuple(self._sanitize(str(a)) for a in record.args)
        return True

    @classmethod
    def _sanitize(cls, text: Any) -> Any:
        if not isinstance(text, str):
            return text
        for pattern in cls.PATTERNS:
            text = pattern.sub("[REDACTED]", text)
        return text

    @classmethod
    def install_sanitizer(cls, logger_name: str) -> None:
        """Add SanitizingFilter to the named logger (idempotent)."""
        target = logging.getLogger(logger_name)
        if not any(isinstance(f, cls) for f in target.filters):
            target.addFilter(cls())


# ── SecureConfig ─────────────────────────────────────────────────────


class SecureConfig:
    """4-tier credential resolution: env -> config -> vault -> prompt.

    Never logs secret values — only tier name and key name.
    """

    TIERS = ["env", "config", "vault", "prompt"]

    def __init__(self) -> None:
        self._vault_provider: Optional[VaultProvider] = None

    def set_vault_provider(self, provider: VaultProvider) -> None:
        """Set the vault backend for tier-3 resolution."""
        self._vault_provider = provider

    def resolve(self, key: str) -> Optional[str]:
        """Try each tier in order, return first non-None value."""
        for tier in self.TIERS:
            method = getattr(self, f"_resolve_{tier}")
            value = method(key)
            if value is not None:
                logger.info("Resolved key '%s' via tier '%s'", key, tier)
                return value
        logger.info("Key '%s' not resolved in any tier", key)
        return None

    # ── Tier implementations ──

    def _resolve_env(self, key: str) -> Optional[str]:
        """Tier 1: environment variable."""
        return os.environ.get(key)

    def _resolve_config(self, key: str) -> Optional[str]:
        """Tier 2: ~/.3surgeons/config.yaml under secrets: key."""
        try:
            import yaml  # type: ignore
        except ImportError:
            return None
        config_path = os.path.expanduser("~/.3surgeons/config.yaml")
        if not os.path.isfile(config_path):
            return None
        try:
            with open(config_path, "r") as f:
                data = yaml.safe_load(f)
            if isinstance(data, dict):
                secrets = data.get("secrets")
                if isinstance(secrets, dict):
                    val = secrets.get(key)
                    return str(val) if val is not None else None
        except Exception as exc:
            logger.debug("Config tier failed for '%s': %s", key, exc)
        return None

    def _resolve_vault(self, key: str) -> Optional[str]:
        """Tier 3: vault provider."""
        if self._vault_provider is None:
            return None
        try:
            if not self._vault_provider.is_available():
                return None
            return self._vault_provider.get_secret(key)
        except Exception as exc:
            logger.debug("Vault tier failed for '%s': %s", key, exc)
            return None

    def _resolve_prompt(self, key: str) -> Optional[str]:
        """Tier 4: interactive prompt (only if TTY attached)."""
        if not sys.stdin.isatty():
            return None
        try:
            return getpass.getpass(f"Enter {key}: ")
        except (EOFError, KeyboardInterrupt):
            return None
