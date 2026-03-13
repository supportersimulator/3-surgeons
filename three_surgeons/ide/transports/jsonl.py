"""JSONL file transport — writes events to .projectdna/.events.jsonl."""
from __future__ import annotations

import json
import logging
from dataclasses import asdict
from pathlib import Path

from three_surgeons.ide.event_bus import EventEnvelope

logger = logging.getLogger(__name__)


class JSONLTransport:
    def __init__(self, path: str, max_bytes: int = 1_000_000) -> None:
        self._path = Path(path)
        self._max_bytes = max_bytes

    def deliver(self, event: EventEnvelope) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        if self._path.exists() and self._path.stat().st_size > self._max_bytes:
            self._rotate()
        line = json.dumps(asdict(event)) + "\n"
        with open(self._path, "a") as f:
            f.write(line)

    def _rotate(self) -> None:
        rotated = self._path.with_suffix(".jsonl.old")
        try:
            if rotated.exists():
                rotated.unlink()
            self._path.rename(rotated)
        except OSError:
            logger.warning("JSONL rotation failed", exc_info=True)
