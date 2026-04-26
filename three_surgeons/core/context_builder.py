"""Build RuntimeContext from Config by probing infrastructure.

Detects: healthy LLMs, state backend, evidence store, git availability.
Called once per command invocation.
"""
from __future__ import annotations

import logging
import subprocess
from typing import List, Optional, Tuple

from three_surgeons.core.config import Config
from three_surgeons.core.evidence import EvidenceStore
from three_surgeons.core.models import LLMProvider
from three_surgeons.core.requirements import RuntimeContext
from three_surgeons.core.state import create_backend_from_config

logger = logging.getLogger(__name__)


def _probe_llm_health(config: Config, timeout_s: float = 5.0) -> List[LLMProvider]:
    """Probe configured LLM endpoints and return healthy ones.

    Creates an LLMProvider for each surgeon config (cardiologist, neurologist)
    and calls ping(). Only providers that respond with ok=True are returned.
    """
    healthy: List[LLMProvider] = []
    for name, surgeon_cfg in [
        ("cardiologist", config.cardiologist),
        ("neurologist", config.neurologist),
    ]:
        try:
            provider = LLMProvider(surgeon_cfg, fallbacks=surgeon_cfg.get_fallback_configs())
            resp = provider.ping(timeout_s=timeout_s)
            if resp.ok:
                healthy.append(provider)
            else:
                logger.info("LLM %s unhealthy: %s", name, resp.content[:100])
        except Exception as exc:
            logger.info("LLM %s unreachable: %s", name, exc)
    return healthy


def _detect_git(cwd: Optional[str] = None) -> Tuple[bool, Optional[str]]:
    """Check if cwd is inside a git repo."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            capture_output=True, text=True, timeout=5,
            cwd=cwd,
        )
        if result.returncode == 0:
            return True, result.stdout.strip()
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass
    return False, None


def build_runtime_context(
    config: Config,
    probe_timeout_s: float = 5.0,
    cwd: Optional[str] = None,
) -> RuntimeContext:
    """Build a RuntimeContext by probing all infrastructure."""
    healthy_llms = _probe_llm_health(config, timeout_s=probe_timeout_s)
    state = create_backend_from_config(config.state)
    evidence = EvidenceStore(str(config.evidence.resolved_path))
    git_available, git_root = _detect_git(cwd)

    return RuntimeContext(
        healthy_llms=healthy_llms,
        state=state,
        evidence=evidence,
        git_available=git_available,
        git_root=git_root,
        config=config,
    )
