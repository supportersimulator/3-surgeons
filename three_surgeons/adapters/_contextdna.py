"""ContextDNA adapter — mirrors findings to the local ContextDNA ecosystem."""

from __future__ import annotations

import json
import logging
import urllib.request
import urllib.error
from typing import Any, Dict, Optional

from three_surgeons.adapters._protocol import SurgeryAdapter, Capability

logger = logging.getLogger(__name__)

_error_counts: dict[str, int] = {}

_BASE_URL = "http://127.0.0.1:8080"
_FINDING_ENDPOINT = f"{_BASE_URL}/contextdna/superhero/finding"
_HEALTH_ENDPOINT = f"{_BASE_URL}/health"


class ContextDNAAdapter(SurgeryAdapter):
    """Mirrors surgery findings to the local ContextDNA agent_service."""

    capabilities = Capability.EVIDENCE_MIRROR | Capability.CRITICAL_FINDINGS | Capability.GAINS_GATE
    thread_safe = True
    gate_mode = "warn"

    def on_init(self) -> None:
        try:
            req = urllib.request.Request(_HEALTH_ENDPOINT, method="GET")
            with urllib.request.urlopen(req, timeout=2) as resp:
                if resp.status == 200:
                    logger.debug("ContextDNA agent_service reachable")
                else:
                    logger.warning(
                        "ContextDNA agent_service returned status %d", resp.status
                    )
        except Exception as exc:
            logger.warning("ContextDNA agent_service unreachable: %s", exc)

    def on_cost(self, surgeon: str, cost_usd: float, operation: str) -> None:
        self._post_finding({
            "surgeon": surgeon,
            "cost_usd": cost_usd,
            "operation": operation,
            "type": "cost_telemetry",
        })

    def on_cross_exam_logged(self, topic: str, data: Dict[str, Any]) -> None:
        self._post_finding({
            "topic": topic,
            **data,
            "type": "cross_exam_result",
        })

    def on_error(self, operation: str, error: Exception, context: Dict[str, Any]) -> None:
        self._post_finding({
            "operation": operation,
            "error": str(error),
            "context": context,
            "type": "adapter_error",
        })

    def check_gate(self) -> Optional[str]:
        try:
            req = urllib.request.Request(_HEALTH_ENDPOINT, method="GET")
            with urllib.request.urlopen(req, timeout=2) as resp:
                if resp.status == 200:
                    return None
                return "ContextDNA agent_service unreachable"
        except Exception:
            return "ContextDNA agent_service unreachable"

    def enrich_topic(self, topic: str) -> str:
        return topic

    def on_workflow_start(self, operation: str, context: Dict[str, Any]) -> None:
        pass

    def on_workflow_end(self, operation: str, result: Dict[str, Any]) -> None:
        pass

    def on_user_action(self, action: str, details: Dict[str, Any]) -> None:
        pass

    def close(self) -> None:
        pass

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _post_finding(self, payload: Dict[str, Any]) -> None:
        try:
            body = json.dumps(payload).encode("utf-8")
            req = urllib.request.Request(
                _FINDING_ENDPOINT,
                data=body,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=3):
                pass
        except Exception as exc:
            logger.warning("ContextDNA POST failed: %s", exc)
            _error_counts["ContextDNAAdapter"] = _error_counts.get("ContextDNAAdapter", 0) + 1
