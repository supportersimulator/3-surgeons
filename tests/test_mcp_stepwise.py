"""Tests for stepwise cross-examination MCP tools."""
from __future__ import annotations

import pytest
from unittest.mock import MagicMock, patch

from three_surgeons.mcp.server import (
    _impl_cross_examine_start,
    _impl_cross_examine_deepen,
    _impl_cross_examine_explore,
    _impl_cross_examine_synthesize,
    _impl_cross_examine_iterate,
)
from three_surgeons.core.sessions import LiveSession, SessionManager


def _make_phase_result(phase: str, session_id: str = "test-id", next_action: str = "deepen") -> dict:
    return {
        "session_id": session_id,
        "phase": phase,
        "iteration": 1,
        "cardiologist": {"findings": [f"{phase}-cardio-f1"], "confidence": 0.7, "cost_usd": 0.005, "latency_ms": 1000},
        "neurologist": {"findings": [f"{phase}-neuro-f1"], "signals": [], "cost_usd": 0.0, "latency_ms": 2000},
        "next_action": next_action,
        "warnings": [],
    }


@pytest.fixture
def mock_team():
    team = MagicMock()
    team.phase_start.return_value = _make_phase_result("start", next_action="deepen")
    team.phase_deepen.return_value = _make_phase_result("deepen", next_action="explore")
    team.phase_explore.return_value = _make_phase_result("explore", next_action="synthesize")
    team.phase_synthesize.return_value = _make_phase_result("synthesize", next_action="done")
    team.phase_iterate.return_value = _make_phase_result("start", next_action="deepen")
    return team


@pytest.fixture
def mock_sessions(tmp_path):
    sm = SessionManager(sessions_dir=tmp_path)
    return sm


@patch("three_surgeons.mcp.server._build_surgery_team")
@patch("three_surgeons.mcp.server.SessionManager")
def test_start_creates_session_and_calls_phase(MockSM, mock_build, mock_team, tmp_path):
    """cross_examine_start creates a session, calls phase_start, saves."""
    sm = SessionManager(sessions_dir=tmp_path)
    session = sm.create(topic="test topic", mode="iterative", depth="full", file_paths=[])
    sm.save(session)

    MockSM.return_value = sm
    MockSM.return_value.create = MagicMock(return_value=session)
    MockSM.return_value.save = MagicMock()
    mock_build.return_value = mock_team

    result = _impl_cross_examine_start("test topic", mode="iterative")

    mock_team.phase_start.assert_called_once_with(session)
    MockSM.return_value.save.assert_called_once_with(session)
    assert result["phase"] == "start"
    assert result["next_action"] == "deepen"


@patch("three_surgeons.mcp.server._build_surgery_team")
@patch("three_surgeons.mcp.server.SessionManager")
def test_deepen_loads_and_calls_phase(MockSM, mock_build, mock_team, tmp_path):
    """cross_examine_deepen loads session by id and calls phase_deepen."""
    sm = SessionManager(sessions_dir=tmp_path)
    session = sm.create(topic="test", mode="iterative", depth="full", file_paths=[])
    sm.save(session)

    MockSM.return_value.get = MagicMock(return_value=session)
    MockSM.return_value.save = MagicMock()
    mock_build.return_value = mock_team

    result = _impl_cross_examine_deepen(session.session_id)

    mock_team.phase_deepen.assert_called_once_with(session)
    MockSM.return_value.save.assert_called_once_with(session)
    assert result["phase"] == "deepen"


@patch("three_surgeons.mcp.server._build_surgery_team")
@patch("three_surgeons.mcp.server.SessionManager")
def test_deepen_invalid_session_returns_error(MockSM, mock_build, mock_team):
    """cross_examine_deepen with unknown session_id returns error dict."""
    MockSM.return_value.get = MagicMock(return_value=None)

    result = _impl_cross_examine_deepen("nonexistent-id")

    assert "error" in result
    assert "nonexistent-id" in result["error"]
    mock_team.phase_deepen.assert_not_called()


@patch("three_surgeons.mcp.server._build_surgery_team")
@patch("three_surgeons.mcp.server.SessionManager")
def test_explore_loads_and_calls_phase(MockSM, mock_build, mock_team, tmp_path):
    """cross_examine_explore loads session and calls phase_explore."""
    sm = SessionManager(sessions_dir=tmp_path)
    session = sm.create(topic="test", mode="iterative", depth="full", file_paths=[])
    sm.save(session)

    MockSM.return_value.get = MagicMock(return_value=session)
    MockSM.return_value.save = MagicMock()
    mock_build.return_value = mock_team

    result = _impl_cross_examine_explore(session.session_id)

    mock_team.phase_explore.assert_called_once_with(session)
    assert result["phase"] == "explore"


@patch("three_surgeons.mcp.server._build_surgery_team")
@patch("three_surgeons.mcp.server.SessionManager")
def test_synthesize_loads_and_calls_phase(MockSM, mock_build, mock_team, tmp_path):
    """cross_examine_synthesize loads session and calls phase_synthesize."""
    sm = SessionManager(sessions_dir=tmp_path)
    session = sm.create(topic="test", mode="iterative", depth="full", file_paths=[])
    sm.save(session)

    MockSM.return_value.get = MagicMock(return_value=session)
    MockSM.return_value.save = MagicMock()
    mock_build.return_value = mock_team

    result = _impl_cross_examine_synthesize(session.session_id)

    mock_team.phase_synthesize.assert_called_once_with(session)
    assert result["phase"] == "synthesize"
    assert result["next_action"] == "done"


@patch("three_surgeons.mcp.server._build_surgery_team")
@patch("three_surgeons.mcp.server.SessionManager")
def test_iterate_loads_and_calls_phase(MockSM, mock_build, mock_team, tmp_path):
    """cross_examine_iterate loads session and calls phase_iterate."""
    sm = SessionManager(sessions_dir=tmp_path)
    session = sm.create(topic="test", mode="iterative", depth="full", file_paths=[])
    sm.save(session)

    MockSM.return_value.get = MagicMock(return_value=session)
    MockSM.return_value.save = MagicMock()
    mock_build.return_value = mock_team

    result = _impl_cross_examine_iterate(session.session_id)

    mock_team.phase_iterate.assert_called_once_with(session)
    assert result["phase"] == "start"


@patch("three_surgeons.mcp.server._build_surgery_team")
@patch("three_surgeons.mcp.server.SessionManager")
def test_full_flow_start_to_synthesize(MockSM, mock_build, mock_team, tmp_path):
    """Full flow: start -> deepen -> explore -> synthesize."""
    sm = SessionManager(sessions_dir=tmp_path)
    session = sm.create(topic="architecture review", mode="iterative", depth="full", file_paths=[])
    sm.save(session)

    MockSM.return_value.create = MagicMock(return_value=session)
    MockSM.return_value.get = MagicMock(return_value=session)
    MockSM.return_value.save = MagicMock()
    mock_build.return_value = mock_team

    r1 = _impl_cross_examine_start("architecture review")
    assert r1["next_action"] == "deepen"

    r2 = _impl_cross_examine_deepen(session.session_id)
    assert r2["next_action"] == "explore"

    r3 = _impl_cross_examine_explore(session.session_id)
    assert r3["next_action"] == "synthesize"

    r4 = _impl_cross_examine_synthesize(session.session_id)
    assert r4["next_action"] == "done"

    assert MockSM.return_value.save.call_count == 4


@patch("three_surgeons.mcp.server._build_surgery_team")
@patch("three_surgeons.mcp.server.SessionManager")
def test_explore_invalid_session_returns_error(MockSM, mock_build, mock_team):
    """cross_examine_explore with unknown session returns error."""
    MockSM.return_value.get = MagicMock(return_value=None)
    result = _impl_cross_examine_explore("bad-id")
    assert "error" in result
    assert "bad-id" in result["error"]


@patch("three_surgeons.mcp.server._build_surgery_team")
@patch("three_surgeons.mcp.server.SessionManager")
def test_synthesize_invalid_session_returns_error(MockSM, mock_build, mock_team):
    """cross_examine_synthesize with unknown session returns error."""
    MockSM.return_value.get = MagicMock(return_value=None)
    result = _impl_cross_examine_synthesize("bad-id")
    assert "error" in result


@patch("three_surgeons.mcp.server._build_surgery_team")
@patch("three_surgeons.mcp.server.SessionManager")
def test_iterate_invalid_session_returns_error(MockSM, mock_build, mock_team):
    """cross_examine_iterate with unknown session returns error."""
    MockSM.return_value.get = MagicMock(return_value=None)
    result = _impl_cross_examine_iterate("bad-id")
    assert "error" in result


def test_session_state_persisted_between_calls(tmp_path):
    """Verify session created in start can be loaded in deepen (real SessionManager)."""
    sm = SessionManager(sessions_dir=tmp_path)
    session = sm.create(topic="persistence test", mode="iterative", depth="full", file_paths=[])
    sm.save(session)

    loaded = sm.get(session.session_id)
    assert loaded is not None
    assert loaded.topic == "persistence test"
    assert loaded.session_id == session.session_id
    assert loaded.mode == "iterative"
