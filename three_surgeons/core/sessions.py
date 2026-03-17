# three_surgeons/core/sessions.py
"""Live surgery session state management.

Persists cross-examination state across phased MCP tool calls.
Session files are JSON in ~/.3surgeons/sessions/, auto-cleaned after 24h.
"""
from __future__ import annotations

import json
import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

_MODE_MAX_ITERS = {"single": 1, "iterative": 3, "continuous": 5}
_PHASE_ORDER = ["created", "start", "deepen", "explore", "synthesize"]
_CONSENSUS_THRESHOLD = 0.7


@dataclass
class LiveSession:
    """In-memory representation of a live surgery session."""

    session_id: str
    topic: str
    mode: str
    depth: str
    file_paths: List[str] = field(default_factory=list)
    file_context: str = ""
    current_phase: str = "created"
    current_iteration: int = 1
    accumulated_findings: List[Dict[str, Any]] = field(default_factory=list)
    consensus_scores: List[float] = field(default_factory=list)
    total_cost: float = 0.0
    warnings: List[str] = field(default_factory=list)
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    updated_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    max_iterations: int = 0

    def __post_init__(self) -> None:
        if self.max_iterations == 0:
            self.max_iterations = _MODE_MAX_ITERS.get(self.mode, 1)

    def advance_phase(self, phase: str) -> None:
        if phase not in _PHASE_ORDER:
            raise ValueError(f"Invalid phase {phase!r}, must be one of {_PHASE_ORDER}")
        self.current_phase = phase
        self.updated_at = datetime.now(timezone.utc).isoformat()

    def add_finding(
        self,
        iteration: int,
        phase: str,
        cardiologist: Any = None,
        neurologist: Any = None,
    ) -> None:
        self.accumulated_findings.append({
            "iteration": iteration,
            "phase": phase,
            "cardiologist": cardiologist,
            "neurologist": neurologist,
        })
        self.updated_at = datetime.now(timezone.utc).isoformat()

    def add_consensus_score(self, score: float) -> None:
        self.consensus_scores.append(score)
        self.updated_at = datetime.now(timezone.utc).isoformat()

    def track_cost(self, cost_usd: float) -> None:
        self.total_cost += cost_usd

    def next_action(self) -> str:
        """Determine what should happen next based on current phase."""
        if self.current_phase == "start":
            return "deepen"
        if self.current_phase == "deepen":
            return "explore"
        if self.current_phase == "explore":
            return "synthesize"
        if self.current_phase == "synthesize":
            # Check consensus
            if self.consensus_scores and self.consensus_scores[-1] >= _CONSENSUS_THRESHOLD:
                return "done"
            if self.current_iteration >= self.max_iterations:
                return "done"
            return "iterate"
        return "start"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "session_id": self.session_id,
            "topic": self.topic,
            "mode": self.mode,
            "depth": self.depth,
            "file_paths": self.file_paths,
            "file_context": self.file_context,
            "current_phase": self.current_phase,
            "current_iteration": self.current_iteration,
            "max_iterations": self.max_iterations,
            "accumulated_findings": self.accumulated_findings,
            "consensus_scores": self.consensus_scores,
            "total_cost": self.total_cost,
            "warnings": self.warnings,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> LiveSession:
        return cls(
            session_id=d["session_id"],
            topic=d["topic"],
            mode=d["mode"],
            depth=d["depth"],
            file_paths=d.get("file_paths", []),
            file_context=d.get("file_context", ""),
            current_phase=d.get("current_phase", "created"),
            current_iteration=d.get("current_iteration", 1),
            max_iterations=d.get("max_iterations", 0),
            accumulated_findings=d.get("accumulated_findings", []),
            consensus_scores=d.get("consensus_scores", []),
            total_cost=d.get("total_cost", 0.0),
            warnings=d.get("warnings", []),
            created_at=d.get("created_at", ""),
            updated_at=d.get("updated_at", ""),
        )


class SessionManager:
    """Manages session files on disk."""

    def __init__(self, sessions_dir: Optional[Path] = None) -> None:
        if sessions_dir is None:
            sessions_dir = Path.home() / ".3surgeons" / "sessions"
        self._dir = sessions_dir
        self._dir.mkdir(parents=True, exist_ok=True)

    def create(
        self,
        topic: str,
        mode: str,
        depth: str = "full",
        file_paths: Optional[List[str]] = None,
    ) -> LiveSession:
        session = LiveSession(
            session_id=str(uuid.uuid4()),
            topic=topic,
            mode=mode,
            depth=depth,
            file_paths=file_paths or [],
        )
        self.save(session)
        return session

    def get(self, session_id: str) -> Optional[LiveSession]:
        path = self._dir / f"{session_id}.json"
        if not path.exists():
            return None
        try:
            data = json.loads(path.read_text())
            return LiveSession.from_dict(data)
        except (json.JSONDecodeError, KeyError) as exc:
            logger.warning("Corrupt session file %s: %s", path, exc)
            return None

    def save(self, session: LiveSession) -> None:
        session.updated_at = datetime.now(timezone.utc).isoformat()
        path = self._dir / f"{session.session_id}.json"
        path.write_text(json.dumps(session.to_dict(), indent=2))

    def delete(self, session_id: str) -> None:
        path = self._dir / f"{session_id}.json"
        if path.exists():
            path.unlink()

    def cleanup(self, max_age_hours: int = 24) -> int:
        """Remove sessions older than max_age_hours. Returns count removed."""
        cutoff = datetime.now(timezone.utc) - timedelta(hours=max_age_hours)
        removed = 0
        for path in self._dir.glob("*.json"):
            try:
                data = json.loads(path.read_text())
                created = datetime.fromisoformat(data.get("created_at", ""))
                if created.tzinfo is None:
                    created = created.replace(tzinfo=timezone.utc)
                if created < cutoff:
                    path.unlink()
                    removed += 1
            except Exception as exc:
                logger.warning("Skipping unparseable session file %s: %s", path, exc)
        return removed
