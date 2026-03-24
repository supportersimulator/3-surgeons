"""Auto-detection probes — discover available ecosystem infrastructure."""
from __future__ import annotations

import logging
import os
import subprocess
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


def _probe_redis(timeout_s: float = 1.0) -> bool:
    """Check if Redis is reachable on 127.0.0.1:6379."""
    try:
        import redis
        r = redis.Redis(
            host="127.0.0.1", port=6379,
            decode_responses=True, socket_timeout=timeout_s,
        )
        return r.ping()
    except Exception as exc:
        logger.debug("Redis probe failed: %s", exc)
        return False


def _probe_git() -> bool:
    """Check if current directory is inside a git repository."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--is-inside-work-tree"],
            capture_output=True, text=True, timeout=2,
        )
        return result.returncode == 0 and result.stdout.strip() == "true"
    except Exception as exc:
        logger.debug("Git probe failed: %s", exc)
        return False


def _probe_contextdna(timeout_s: float = 2.0) -> bool:
    """Check if ContextDNA agent_service is running on 127.0.0.1:8080."""
    try:
        import urllib.request
        req = urllib.request.Request(
            "http://127.0.0.1:8080/health",
            method="GET",
        )
        with urllib.request.urlopen(req, timeout=timeout_s) as resp:
            return resp.status == 200
    except Exception as exc:
        logger.debug("ContextDNA probe failed: %s", exc)
        return False


def _probe_observability() -> bool:
    """Check if .observability.db exists in common locations."""
    candidates = [
        os.path.expanduser("~/.context-dna/.observability.db"),
        ".observability.db",
    ]
    for path in candidates:
        if os.path.isfile(path):
            return True
    return False


def auto_detect(config: Optional[Dict[str, Any]] = None) -> Any:
    """Probe available infra and build a CompositeAdapter from what's found.

    Each probe has a short timeout to avoid blocking startup.
    Results are cached for the AdapterContext lifetime (caller responsibility).
    """
    from ._composite import CompositeAdapter
    from ._standalone import StandaloneAdapter

    adapters: list = []

    # Git first — enriches topic for downstream adapters
    if _probe_git():
        try:
            from ._git import GitAdapter
            adapters.append(GitAdapter())
            logger.info("Adapter enabled: GitAdapter")
        except Exception as exc:
            logger.warning("GitAdapter init failed: %s", exc)

    # Redis — cost telemetry + evidence mirroring
    if _probe_redis():
        try:
            from ._redis import RedisAdapter
            adapters.append(RedisAdapter())
            logger.info("Adapter enabled: RedisAdapter")
        except Exception as exc:
            logger.warning("RedisAdapter init failed: %s", exc)

    # ContextDNA — agent_service integration
    if _probe_contextdna():
        try:
            from ._contextdna import ContextDNAAdapter
            adapters.append(ContextDNAAdapter())
            logger.info("Adapter enabled: ContextDNAAdapter")
        except Exception as exc:
            logger.warning("ContextDNAAdapter init failed: %s", exc)

    # Observability — .observability.db mirroring
    if _probe_observability():
        try:
            from ._observability import ObservabilityAdapter
            adapters.append(ObservabilityAdapter())
            logger.info("Adapter enabled: ObservabilityAdapter")
        except Exception as exc:
            logger.warning("ObservabilityAdapter init failed: %s", exc)

    if not adapters:
        logger.info("No ecosystem infra detected, using StandaloneAdapter")
        return StandaloneAdapter()

    logger.info("Built CompositeAdapter with %d adapter(s): %s",
                len(adapters),
                ", ".join(type(a).__name__ for a in adapters))
    return CompositeAdapter(adapters)
