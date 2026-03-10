# three_surgeons/core/upgrade.py
"""Upgrade adaptability engine.

Detects ecosystem state, manages upgrade transactions, handles
crash recovery, and orchestrates phase transitions.
"""
from __future__ import annotations

import enum
import hashlib
import json
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

import httpx

from three_surgeons.core.config import Config, detect_local_backend


class InfraCapability(enum.Enum):
    """Detectable infrastructure capabilities."""

    LOCAL_LLM = "local_llm"
    REDIS = "redis"
    CONTEXTDNA = "contextdna"
    IDE_EVENT_BUS = "ide_event_bus"


@dataclass
class ProbeResult:
    """Result of an ecosystem probe."""

    detected_phase: int = 1
    capabilities: List[InfraCapability] = field(default_factory=list)
    details: Dict[str, Any] = field(default_factory=dict)
    timestamp: float = field(default_factory=time.time)


class EcosystemProbe:
    """Probes the local environment for available infrastructure.

    Checks: local LLMs, Redis, ContextDNA adapter, IDE event bus.
    Determines the highest phase the system can support.
    """

    def __init__(self, timeout: float = 2.0) -> None:
        self._timeout = timeout

    def run(self) -> ProbeResult:
        """Run all probes and determine detected phase."""
        result = ProbeResult()

        # Check local LLM backends
        backends = detect_local_backend(timeout_s=self._timeout)
        if backends:
            result.capabilities.append(InfraCapability.LOCAL_LLM)
            result.details["local_backends"] = [b["provider"] for b in backends]

        # Check Redis
        if self._check_redis():
            result.capabilities.append(InfraCapability.REDIS)

        # Check ContextDNA
        if self._check_contextdna():
            result.capabilities.append(InfraCapability.CONTEXTDNA)

        # Check IDE event bus
        if self._check_ide_event_bus():
            result.capabilities.append(InfraCapability.IDE_EVENT_BUS)

        # Determine phase
        if InfraCapability.IDE_EVENT_BUS in result.capabilities:
            result.detected_phase = 3
        elif (InfraCapability.REDIS in result.capabilities
              or InfraCapability.CONTEXTDNA in result.capabilities):
            result.detected_phase = 2
        else:
            result.detected_phase = 1

        return result

    def _check_redis(self) -> bool:
        """Ping Redis on default port."""
        try:
            import redis
            client = redis.Redis(host="127.0.0.1", port=6379, socket_timeout=self._timeout)
            return client.ping()
        except Exception:
            return False

    def _check_contextdna(self) -> bool:
        """Check for ContextDNA adapter (env var or port 8029)."""
        if os.environ.get("CONTEXTDNA_ADAPTER"):
            return True
        try:
            resp = httpx.get(
                "http://127.0.0.1:8029/health",
                timeout=self._timeout,
            )
            return resp.status_code == 200
        except Exception:
            return False

    def _check_ide_event_bus(self) -> bool:
        """Check for IDE event bus (future -- Phase 3)."""
        # Phase 3: check for Electron IPC or event bus socket
        return os.environ.get("CONTEXTDNA_IDE_BUS") is not None
