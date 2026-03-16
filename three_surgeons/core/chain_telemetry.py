"""Chain execution telemetry — recording, pattern detection, dependency discovery.

Records every chain execution to StateBackend. After sufficient observations,
detects common segment orderings and dependency correlations.
"""
from __future__ import annotations

import hashlib
import json
import logging
import time
import uuid
from collections import Counter
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional

from three_surgeons.core.state import StateBackend

logger = logging.getLogger(__name__)


class EvidenceGrade(Enum):
    """Evidence strength for learned patterns."""

    ANECDOTE = "anecdote"
    CORRELATION = "correlation"
    CASE_SERIES = "case_series"
    COHORT = "cohort"

    @classmethod
    def for_observations(cls, count: int, frequency: float) -> "EvidenceGrade":
        """Determine grade from observation count and frequency."""
        if count >= 50 and frequency >= 0.95:
            return cls.COHORT
        if count >= 20 and frequency >= 0.85:
            return cls.CASE_SERIES
        if count >= 5 and frequency >= 0.70:
            return cls.CORRELATION
        return cls.ANECDOTE


@dataclass
class ExecutionRecord:
    """What's captured per chain run."""

    chain_id: str
    execution_id: str
    segments_run: List[str]
    segments_skipped: List[str]
    order_digest: str
    success: bool
    failed_segment: Optional[str]
    duration_ms: float
    duration_by_segment: Dict[str, float]
    project_id: str
    timestamp: float

    @classmethod
    def create(
        cls,
        chain_id: str,
        segments_run: List[str],
        segments_skipped: List[str],
        success: bool,
        duration_ms: float,
        duration_by_segment: Dict[str, float],
        project_id: str = "",
        failed_segment: Optional[str] = None,
    ) -> "ExecutionRecord":
        order_hash = hashlib.sha256(
            ",".join(segments_run).encode()
        ).hexdigest()[:16]
        return cls(
            chain_id=chain_id,
            execution_id=uuid.uuid4().hex[:12],
            segments_run=segments_run,
            segments_skipped=segments_skipped,
            order_digest=order_hash,
            success=success,
            failed_segment=failed_segment,
            duration_ms=duration_ms,
            duration_by_segment=duration_by_segment,
            project_id=project_id,
            timestamp=time.time(),
        )

    def to_json(self) -> str:
        return json.dumps({
            "chain_id": self.chain_id,
            "execution_id": self.execution_id,
            "segments_run": self.segments_run,
            "segments_skipped": self.segments_skipped,
            "order_digest": self.order_digest,
            "success": self.success,
            "failed_segment": self.failed_segment,
            "duration_ms": self.duration_ms,
            "duration_by_segment": self.duration_by_segment,
            "project_id": self.project_id,
            "timestamp": self.timestamp,
        })

    @classmethod
    def from_json(cls, raw: str) -> "ExecutionRecord":
        d = json.loads(raw)
        return cls(**d)


@dataclass
class DetectedPattern:
    """A discovered segment ordering pattern."""

    order_digest: str
    segments: List[str]
    frequency: float
    observations: int
    grade: EvidenceGrade


class ChainTelemetry:
    """Records executions and detects patterns."""

    def __init__(self, state: StateBackend) -> None:
        self._state = state

    def record(self, rec: ExecutionRecord) -> None:
        """Write execution record to state backend."""
        self._state.sorted_set_add(
            f"telemetry:execs_by_chain:{rec.chain_id}",
            rec.to_json(),
            rec.timestamp,
        )

    def recent_executions(
        self,
        chain_id: str,
        limit: int = 20,
        max_age_s: float = 604800,  # 7 days
    ) -> List[ExecutionRecord]:
        """Retrieve recent executions for a chain."""
        now = time.time()
        raw = self._state.sorted_set_range(
            f"telemetry:execs_by_chain:{chain_id}",
            min_score=now - max_age_s,
            max_score=now,
            limit=limit,
        )
        records = []
        for member, _score in raw:
            try:
                records.append(ExecutionRecord.from_json(member))
            except (json.JSONDecodeError, TypeError, KeyError):
                logger.warning("Failed to deserialize execution record")
                continue
        return records

    def detect_patterns(
        self,
        chain_id: str,
        min_observations: int = 5,
        min_frequency: float = 0.75,
    ) -> List[DetectedPattern]:
        """Find common segment orderings not yet named as presets."""
        execs = self.recent_executions(chain_id, limit=100)
        if len(execs) < min_observations:
            return []

        order_counts: Counter = Counter()
        digest_to_segments: Dict[str, List[str]] = {}
        for rec in execs:
            order_counts[rec.order_digest] += 1
            digest_to_segments[rec.order_digest] = rec.segments_run

        total = len(execs)
        patterns = []
        for digest, count in order_counts.items():
            freq = count / total
            if freq >= min_frequency:
                grade = EvidenceGrade.for_observations(count, freq)
                patterns.append(DetectedPattern(
                    order_digest=digest,
                    segments=digest_to_segments[digest],
                    frequency=freq,
                    observations=count,
                    grade=grade,
                ))
        return patterns
