"""GitAdapter — enriches topics with git context (recent changes, blame)."""
from __future__ import annotations

import logging
import subprocess
from typing import Any, Dict, Optional

from ._protocol import Capability, SurgeryAdapter

logger = logging.getLogger(__name__)


class GitAdapter:
    """Enriches cross-exam topics with relevant git context.

    Adds recent commit summaries and changed files to help surgeons
    understand the current state of the codebase.

    Ordering: This adapter should run FIRST in CompositeAdapter
    so downstream adapters receive enriched topics.
    """

    def __init__(self, max_commits: int = 5) -> None:
        self._max_commits = max_commits

    @property
    def capabilities(self) -> Capability:
        return Capability.GIT_CONTEXT

    @property
    def thread_safe(self) -> bool:
        return True

    def on_init(self) -> None:
        pass

    def on_workflow_start(self, operation: str, topic: str) -> None:
        pass

    def on_workflow_end(self, operation: str, topic: str, result: Any,
                        error: Optional[Exception] = None) -> None:
        pass

    def on_cost(self, surgeon: str, cost_usd: float, operation: str) -> None:
        pass

    def on_cross_exam_logged(self, topic: str, data: Dict[str, Any]) -> None:
        pass

    def on_error(self, operation: str, error: Exception,
                 context: Dict[str, Any]) -> None:
        pass

    def enrich_topic(self, topic: str, operation: str) -> str:
        """Prepend recent git context to topic for cross-exam operations."""
        if operation not in ("cross_examine", "consult", "consensus"):
            return topic

        context_parts = []

        # Recent commits
        commits = self._get_recent_commits()
        if commits:
            context_parts.append(f"Recent commits:\n{commits}")

        # Changed files (unstaged)
        changed = self._get_changed_files()
        if changed:
            context_parts.append(f"Changed files:\n{changed}")

        if not context_parts:
            return topic

        git_context = "\n".join(context_parts)
        return f"[Git Context]\n{git_context}\n\n[Topic]\n{topic}"

    def check_gate(self, operation: str) -> Optional[str]:
        return None

    def on_user_action(self, action: str, metadata: Dict[str, Any]) -> None:
        pass

    def close(self) -> None:
        pass

    def _get_recent_commits(self) -> str:
        try:
            result = subprocess.run(
                ["git", "log", f"--max-count={self._max_commits}",
                 "--oneline", "--no-decorate"],
                capture_output=True, text=True, timeout=3,
            )
            if result.returncode == 0:
                return result.stdout.strip()
        except Exception as exc:
            logger.debug("Git log failed: %s", exc)
        return ""

    def _get_changed_files(self) -> str:
        try:
            result = subprocess.run(
                ["git", "diff", "--name-only", "--diff-filter=ACMR"],
                capture_output=True, text=True, timeout=3,
            )
            if result.returncode == 0:
                return result.stdout.strip()
        except Exception as exc:
            logger.debug("Git diff failed: %s", exc)
        return ""
