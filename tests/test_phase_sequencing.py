# tests/test_phase_sequencing.py
"""Phase sequencing guard tests.

Verifies that LiveSession.advance_phase() enforces the correct phase order:
  created -> start -> deepen -> explore -> synthesize
and that iteration resets (synthesize -> start) work correctly.
"""
from __future__ import annotations

import pytest

from three_surgeons.core.sessions import LiveSession, _PHASE_ORDER


def _make_session(mode: str = "iterative") -> LiveSession:
    return LiveSession(session_id="test", topic="t", mode=mode, depth="full")


class TestPhaseOrdering:
    """advance_phase() must enforce sequential progression."""

    def test_happy_path_full_sequence(self):
        """created -> start -> deepen -> explore -> synthesize succeeds."""
        s = _make_session()
        for phase in _PHASE_ORDER[1:]:  # skip "created" (initial state)
            s.advance_phase(phase)
            assert s.current_phase == phase

    def test_skip_forward_raises(self):
        """Jumping from created directly to explore is rejected."""
        s = _make_session()
        with pytest.raises(ValueError, match="Cannot transition"):
            s.advance_phase("explore")

    def test_skip_forward_from_start(self):
        """start -> synthesize (skipping deepen+explore) is rejected."""
        s = _make_session()
        s.advance_phase("start")
        with pytest.raises(ValueError, match="Cannot transition"):
            s.advance_phase("synthesize")

    def test_backward_transition_raises(self):
        """deepen -> start (going backward) is rejected."""
        s = _make_session()
        s.advance_phase("start")
        s.advance_phase("deepen")
        with pytest.raises(ValueError, match="Cannot transition"):
            s.advance_phase("start")

    def test_same_phase_raises(self):
        """start -> start (no-op) is rejected."""
        s = _make_session()
        s.advance_phase("start")
        with pytest.raises(ValueError, match="Cannot transition"):
            s.advance_phase("start")

    def test_invalid_phase_name_raises(self):
        """Completely unknown phase name is rejected."""
        s = _make_session()
        with pytest.raises(ValueError, match="Invalid phase"):
            s.advance_phase("bogus")

    def test_created_to_deepen_skips_start(self):
        """created -> deepen (skipping start) is rejected."""
        s = _make_session()
        with pytest.raises(ValueError, match="Cannot transition"):
            s.advance_phase("deepen")


class TestIterationReset:
    """synthesize -> start is allowed for iteration, with boundary checks."""

    def test_synthesize_to_start_allowed(self):
        """Iteration reset: synthesize -> start succeeds."""
        s = _make_session()
        # Walk to synthesize
        for phase in ["start", "deepen", "explore", "synthesize"]:
            s.advance_phase(phase)
        # Iteration reset
        s.advance_phase("start")
        assert s.current_phase == "start"

    def test_full_two_iteration_cycle(self):
        """Two complete iteration cycles succeed."""
        s = _make_session()
        # First iteration: created -> start -> deepen -> explore -> synthesize
        for phase in ["start", "deepen", "explore", "synthesize"]:
            s.advance_phase(phase)
        # Iteration reset: synthesize -> start
        s.current_iteration += 1
        s.advance_phase("start")
        # Second iteration: start -> deepen -> explore -> synthesize
        for phase in ["deepen", "explore", "synthesize"]:
            s.advance_phase(phase)

    def test_phase_iterate_resets_to_start(self):
        """Simulates what SurgeryTeam.phase_iterate does: increment + reset."""
        s = _make_session()
        for phase in ["start", "deepen", "explore", "synthesize"]:
            s.advance_phase(phase)
        assert s.current_iteration == 1
        # Mimic phase_iterate logic
        s.current_iteration += 1
        s.advance_phase("start")
        assert s.current_phase == "start"
        assert s.current_iteration == 2


class TestMaxIterations:
    """max_iterations boundary enforcement via next_action()."""

    def test_single_mode_max_1(self):
        s = _make_session(mode="single")
        assert s.max_iterations == 1

    def test_iterative_mode_max_3(self):
        s = _make_session(mode="iterative")
        assert s.max_iterations == 3

    def test_continuous_mode_max_5(self):
        s = _make_session(mode="continuous")
        assert s.max_iterations == 5

    def test_at_max_iterations_returns_done(self):
        """When current_iteration == max_iterations, next_action is 'done' even without consensus."""
        s = _make_session(mode="single")  # max=1
        for phase in ["start", "deepen", "explore", "synthesize"]:
            s.advance_phase(phase)
        s.add_consensus_score(0.3)  # below threshold
        assert s.next_action() == "done"

    def test_below_max_iterations_returns_iterate(self):
        """When current_iteration < max_iterations and no consensus, returns 'iterate'."""
        s = _make_session(mode="iterative")  # max=3
        for phase in ["start", "deepen", "explore", "synthesize"]:
            s.advance_phase(phase)
        s.add_consensus_score(0.3)
        assert s.next_action() == "iterate"

    def test_consensus_reached_returns_done_before_max(self):
        """High consensus score -> done, even if iterations remain."""
        s = _make_session(mode="iterative")
        for phase in ["start", "deepen", "explore", "synthesize"]:
            s.advance_phase(phase)
        s.add_consensus_score(0.85)
        assert s.next_action() == "done"


class TestNextAction:
    """next_action() returns correct values at each phase."""

    def test_created_returns_start(self):
        s = _make_session()
        assert s.current_phase == "created"
        assert s.next_action() == "start"

    def test_start_returns_deepen(self):
        s = _make_session()
        s.advance_phase("start")
        assert s.next_action() == "deepen"

    def test_deepen_returns_explore(self):
        s = _make_session()
        s.advance_phase("start")
        s.advance_phase("deepen")
        assert s.next_action() == "explore"

    def test_explore_returns_synthesize(self):
        s = _make_session()
        s.advance_phase("start")
        s.advance_phase("deepen")
        s.advance_phase("explore")
        assert s.next_action() == "synthesize"

    def test_synthesize_no_scores_returns_iterate(self):
        """No consensus scores at all and iteration remaining -> iterate."""
        s = _make_session(mode="iterative")
        for phase in ["start", "deepen", "explore", "synthesize"]:
            s.advance_phase(phase)
        # No consensus scores added
        assert s.next_action() == "iterate"
