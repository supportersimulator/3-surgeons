"""Config resolution cascade: ENV → TOML → convention → interactive.

Discovers infrastructure (Redis, ContextDNA) and populates
StateConfig/QueueConfig for the 3-Surgeons system.
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

try:
    import tomllib as _tomllib
except ImportError:
    try:
        import tomli as _tomllib  # type: ignore[no-redef]
    except ImportError:
        _tomllib = None  # type: ignore[assignment]


def _load_toml(path: Path) -> Dict[str, Any]:
    """Load a TOML file. Uses tomllib (3.11+) or tomli fallback."""
    if _tomllib is None:
        return _parse_simple_toml(path)

    with open(path, "rb") as f:
        return _tomllib.load(f)


def _parse_simple_toml(path: Path) -> Dict[str, Any]:
    """Minimal TOML parser for [section] + key = "value" patterns."""
    result: Dict[str, Any] = {}
    current_section: Optional[str] = None
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("[") and line.endswith("]"):
            current_section = line[1:-1].strip()
            result[current_section] = {}
        elif "=" in line and current_section:
            key, _, val = line.partition("=")
            key = key.strip()
            val = val.strip().strip('"').strip("'")
            if val.lower() == "true":
                val = True
            elif val.lower() == "false":
                val = False
            result[current_section][key] = val
    return result


@dataclass
class ResolvedStateConfig:
    """Resolved state backend configuration."""
    backend: str = "sqlite"
    redis_url: str = "redis://localhost:6379/0"
    sqlite_path: str = "~/.3-surgeons/state.db"


@dataclass
class ResolvedQueueConfig:
    """Resolved queue/lock backend configuration."""
    backend: str = "local"
    redis_url: str = "redis://localhost:6379/0"
    key_prefix: str = "3surgeons:gpu_lock"


@dataclass
class ResolvedContextDNAConfig:
    """Resolved ContextDNA integration configuration."""
    url: str = "http://localhost:8029"
    enabled: bool = False
    capabilities: Dict[str, Any] = field(default_factory=dict)


class ConfigResolver:
    """Resolves configuration via cascade: ENV → TOML → convention → interactive.

    Args:
        config_dir: Directory containing config.toml (default: ~/.3-surgeons/)
        probe: Whether to probe convention ports (default: True)
    """

    CONFIG_FILENAME = "config.toml"

    def __init__(
        self,
        config_dir: Optional[Path] = None,
        probe: bool = True,
    ) -> None:
        self._config_dir = config_dir or Path.home() / ".3-surgeons"
        self._config_path = self._config_dir / self.CONFIG_FILENAME
        self._probe = probe
        self._toml_data: Optional[Dict[str, Any]] = None
        self._load_toml_file()

    def _load_toml_file(self) -> None:
        """Load TOML config file if it exists."""
        if self._config_path.is_file():
            try:
                self._toml_data = _load_toml(self._config_path)
            except Exception:
                logger.warning("Failed to parse %s", self._config_path, exc_info=True)
                self._toml_data = None

    def _probe_redis(self) -> bool:
        """Probe Redis on localhost:6379 with PING."""
        try:
            import redis
            client = redis.Redis(host="127.0.0.1", port=6379, socket_timeout=2.0)
            return client.ping()
        except Exception:
            return False

    def _probe_contextdna(self) -> bool:
        """Probe ContextDNA on localhost:8029/health."""
        try:
            import httpx
            resp = httpx.get("http://127.0.0.1:8029/health", timeout=2.0)
            return resp.status_code == 200
        except Exception:
            return False

    def resolve_state(self) -> ResolvedStateConfig:
        """Resolve state backend config via cascade."""
        config = ResolvedStateConfig()
        has_toml_backend = False

        # Layer 1: TOML defaults
        if self._toml_data and "state" in self._toml_data:
            section = self._toml_data["state"]
            if "backend" in section:
                config.backend = section["backend"]
                has_toml_backend = True
            if "redis_url" in section:
                config.redis_url = section["redis_url"]
            if "sqlite_path" in section:
                config.sqlite_path = section["sqlite_path"]

        # Layer 0.5: Convention probing (only if no explicit TOML backend)
        if self._probe and not has_toml_backend:
            if self._probe_redis():
                config.backend = "redis"

        # Layer 0: ENV overrides (highest priority)
        env_redis = os.environ.get("THREE_SURGEONS_REDIS_URL")
        if env_redis:
            config.backend = "redis"
            config.redis_url = env_redis

        env_backend = os.environ.get("THREE_SURGEONS_STATE_BACKEND")
        if env_backend:
            config.backend = env_backend

        return config

    def resolve_queue(self) -> ResolvedQueueConfig:
        """Resolve queue/lock backend config via cascade."""
        config = ResolvedQueueConfig()

        # Layer 1: TOML
        if self._toml_data and "queue" in self._toml_data:
            section = self._toml_data["queue"]
            if "backend" in section:
                config.backend = section["backend"]
            if "redis_url" in section:
                config.redis_url = section["redis_url"]
            if "key_prefix" in section:
                config.key_prefix = section["key_prefix"]

        # Layer 0: ENV
        env_redis = os.environ.get("THREE_SURGEONS_REDIS_URL")
        if env_redis:
            config.redis_url = env_redis

        env_queue = os.environ.get("THREE_SURGEONS_QUEUE_BACKEND")
        if env_queue:
            config.backend = env_queue

        return config

    def resolve_contextdna(self) -> ResolvedContextDNAConfig:
        """Resolve ContextDNA integration config via cascade."""
        config = ResolvedContextDNAConfig()
        has_toml_enabled = False

        # Layer 1: TOML
        if self._toml_data and "contextdna" in self._toml_data:
            section = self._toml_data["contextdna"]
            if "url" in section:
                config.url = section["url"]
            if "enabled" in section:
                config.enabled = bool(section["enabled"])
                has_toml_enabled = True

        # Convention probe (only if no explicit TOML setting)
        if self._probe and not has_toml_enabled:
            if self._probe_contextdna():
                config.enabled = True

        # Layer 0: ENV
        env_url = os.environ.get("THREE_SURGEONS_CONTEXTDNA_URL")
        if env_url:
            config.url = env_url
            config.enabled = True

        return config

    def _fetch_capabilities(self, url: str) -> Optional[Dict[str, Any]]:
        """GET /capabilities from a backend service."""
        try:
            import httpx
            resp = httpx.get(f"{url.rstrip('/')}/capabilities", timeout=3.0)
            if resp.status_code == 200:
                return resp.json()
        except Exception:
            logger.debug("Capability fetch failed for %s", url, exc_info=True)
        return None

    def negotiate_capabilities(self, url: str) -> Optional[Dict[str, Any]]:
        """Negotiate capabilities with a backend service.

        Returns the capability response dict, or None if the service
        doesn't respond or doesn't support the protocol.
        """
        return self._fetch_capabilities(url)

    @staticmethod
    def has_capability(caps: Optional[Dict[str, Any]], feature: str) -> bool:
        """Check if a capability response includes a specific feature."""
        if caps is None:
            return False
        return feature in caps.get("features", [])

    def write_toml(self, updates: Dict[str, Dict[str, Any]]) -> None:
        """Write/update sections in config.toml.

        Args:
            updates: Dict of {section: {key: value}} to write/merge.
        """
        self._config_dir.mkdir(parents=True, exist_ok=True)

        # Merge with existing
        data = dict(self._toml_data) if self._toml_data else {}
        for section, values in updates.items():
            if section not in data:
                data[section] = {}
            data[section].update(values)

        # Write simple TOML
        lines = []
        for section, values in data.items():
            lines.append(f"[{section}]")
            for key, val in values.items():
                if isinstance(val, bool):
                    lines.append(f"{key} = {str(val).lower()}")
                elif isinstance(val, (int, float)):
                    lines.append(f"{key} = {val}")
                else:
                    lines.append(f'{key} = "{val}"')
            lines.append("")

        self._config_path.write_text("\n".join(lines) + "\n")
        self._toml_data = data
