# tests/test_sessions.py
"""Tests for live surgery session state management."""
from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

from three_surgeons.core.sessions import LiveSession, SessionManager


class TestSessionManager:
    """Session CRUD and lifecycle."""

    @pytest.fixture
    def manager(self, tmp_path):
        return SessionManager(sessions_dir=tmp_path)

    def test_create_session_returns_live_session(self, manager):
        session = manager.create(
            topic="Should we use SQLite?",
            mode="iterative",
            depth="full",
            file_paths=["/tmp/foo.py"],
        )
        assert isinstance(session, LiveSession)
        assert session.topic == "Should we use SQLite?"
        assert session.mode == "iterative"
        assert session.current_phase == "created"
        assert session.current_iteration == 1
        assert session.max_iterations == 3

    def test_create_session_persists_to_disk(self, manager, tmp_path):
        session = manager.create(topic="test", mode="single", depth="full")
        path = tmp_path / f"{session.session_id}.json"
        assert path.exists()
        data = json.loads(path.read_text())
        assert data["topic"] == "test"

    def test_get_session_by_id(self, manager):
        session = manager.create(topic="test", mode="single", depth="full")
        loaded = manager.get(session.session_id)
        assert loaded is not None
        assert loaded.topic == "test"
        assert loaded.session_id == session.session_id

    def test_get_nonexistent_returns_none(self, manager):
        assert manager.get("nonexistent-id") is None

    def test_save_updates_existing_session(self, manager, tmp_path):
        session = manager.create(topic="test", mode="iterative", depth="full")
        session.current_phase = "deepen"
        session.accumulated_findings.append({
            "iteration": 1, "phase": "start",
            "cardiologist": "analysis A", "neurologist": "analysis B",
        })
        manager.save(session)
        loaded = manager.get(session.session_id)
        assert loaded.current_phase == "deepen"
        assert len(loaded.accumulated_findings) == 1

    def test_delete_removes_session(self, manager, tmp_path):
        session = manager.create(topic="test", mode="single", depth="full")
        manager.delete(session.session_id)
        assert manager.get(session.session_id) is None

    def test_cleanup_old_sessions(self, manager, tmp_path):
        session = manager.create(topic="old", mode="single", depth="full")
        # Manually backdate the file
        path = tmp_path / f"{session.session_id}.json"
        data = json.loads(path.read_text())
        data["created_at"] = "2020-01-01T00:00:00"
        path.write_text(json.dumps(data))
        removed = manager.cleanup(max_age_hours=1)
        assert removed == 1
        assert manager.get(session.session_id) is None


class TestLiveSession:
    """Session data model and transitions."""

    def test_mode_to_max_iterations(self):
        s = LiveSession(session_id="x", topic="t", mode="single", depth="full")
        assert s.max_iterations == 1
        s2 = LiveSession(session_id="x", topic="t", mode="iterative", depth="full")
        assert s2.max_iterations == 3
        s3 = LiveSession(session_id="x", topic="t", mode="continuous", depth="full")
        assert s3.max_iterations == 5

    def test_advance_phase(self):
        s = LiveSession(session_id="x", topic="t", mode="iterative", depth="full")
        s.advance_phase("start")
        assert s.current_phase == "start"
        s.advance_phase("deepen")
        assert s.current_phase == "deepen"

    def test_add_finding(self):
        s = LiveSession(session_id="x", topic="t", mode="iterative", depth="full")
        s.add_finding(
            iteration=1, phase="start",
            cardiologist={"findings": ["A"]},
            neurologist={"findings": ["B"]},
        )
        assert len(s.accumulated_findings) == 1
        assert s.accumulated_findings[0]["phase"] == "start"

    def test_add_consensus_score(self):
        s = LiveSession(session_id="x", topic="t", mode="iterative", depth="full")
        s.add_consensus_score(0.65)
        assert s.consensus_scores == [0.65]

    def test_to_dict_roundtrip(self):
        s = LiveSession(session_id="abc", topic="test", mode="iterative", depth="full")
        s.add_finding(1, "start", {"f": "a"}, {"f": "b"})
        d = s.to_dict()
        s2 = LiveSession.from_dict(d)
        assert s2.session_id == "abc"
        assert s2.topic == "test"
        assert len(s2.accumulated_findings) == 1

    def test_next_action_after_start(self):
        s = LiveSession(session_id="x", topic="t", mode="iterative", depth="full")
        s.advance_phase("start")
        assert s.next_action() == "deepen"

    def test_next_action_after_synthesize_below_threshold(self):
        s = LiveSession(session_id="x", topic="t", mode="iterative", depth="full")
        s.current_iteration = 1
        for phase in ["start", "deepen", "explore", "synthesize"]:
            s.advance_phase(phase)
        s.add_consensus_score(0.4)
        assert s.next_action() == "iterate"

    def test_next_action_after_synthesize_at_max(self):
        s = LiveSession(session_id="x", topic="t", mode="iterative", depth="full")
        s.current_iteration = 3
        for phase in ["start", "deepen", "explore", "synthesize"]:
            s.advance_phase(phase)
        s.add_consensus_score(0.4)
        assert s.next_action() == "done"

    def test_next_action_consensus_reached(self):
        s = LiveSession(session_id="x", topic="t", mode="iterative", depth="full")
        s.current_iteration = 1
        for phase in ["start", "deepen", "explore", "synthesize"]:
            s.advance_phase(phase)
        s.add_consensus_score(0.85)
        assert s.next_action() == "done"

    def test_track_cost(self):
        s = LiveSession(session_id="x", topic="t", mode="single", depth="full")
        s.track_cost(0.005)
        s.track_cost(0.003)
        assert s.total_cost == pytest.approx(0.008)
