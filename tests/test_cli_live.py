"""Tests for the --live flag on the cross-exam CLI command."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

from click.testing import CliRunner

from three_surgeons.cli.main import cli


class TestCrossExamLiveFlag:
    """Test that --live flag is properly wired into cross-exam."""

    def test_live_flag_in_help(self) -> None:
        runner = CliRunner()
        result = runner.invoke(cli, ["cross-exam", "--help"])
        assert result.exit_code == 0
        assert "--live" in result.output
        assert "Phased execution" in result.output

    def test_existing_flags_unchanged(self) -> None:
        runner = CliRunner()
        result = runner.invoke(cli, ["cross-exam", "--help"])
        assert "--mode" in result.output
        assert "--files" in result.output
        assert "--dry-run" in result.output

    @patch("three_surgeons.cli.main.create_backend_from_config")
    @patch("three_surgeons.cli.main._make_neuro")
    @patch("three_surgeons.cli.main.EvidenceStore")
    @patch("three_surgeons.cli.main.LLMProvider")
    @patch("three_surgeons.core.cross_exam.SurgeryTeam")
    @patch("three_surgeons.core.sessions.SessionManager")
    def test_live_runs_phased_approach(
        self,
        mock_session_mgr_cls,
        mock_team_cls,
        mock_llm,
        mock_evidence,
        mock_neuro,
        mock_backend,
        tmp_path,
    ) -> None:
        """--live should use SessionManager + phase_* methods."""
        # Set up mock session
        mock_session = MagicMock()
        mock_session.consensus_scores = [0.85]
        mock_session.total_cost = 0.0042
        mock_session.session_id = "test-123"

        mock_sessions = MagicMock()
        mock_sessions.create.return_value = mock_session
        mock_session_mgr_cls.return_value = mock_sessions

        # Set up mock team with phase methods
        mock_team = MagicMock()
        phase_result = {
            "cardiologist": {
                "findings": ["finding-1"],
                "confidence": 0.9,
                "latency_ms": 120,
            },
            "neurologist": {
                "findings": ["finding-2"],
                "confidence": 0.85,
                "latency_ms": 80,
            },
            "next_action": "done",
            "consensus_scores": [0.85],
        }
        mock_team.phase_start.return_value = phase_result
        mock_team.phase_deepen.return_value = phase_result
        mock_team.phase_explore.return_value = phase_result
        mock_team.phase_synthesize.return_value = phase_result
        mock_team_cls.return_value = mock_team

        runner = CliRunner()
        with patch("three_surgeons.cli.main.Config") as mock_config_cls:
            mock_config = MagicMock()
            mock_config.review.depth = "single"
            mock_config_cls.load.return_value = mock_config

            result = runner.invoke(
                cli,
                ["cross-exam", "--live", "test topic"],
                obj={"config": mock_config},
            )

        assert result.exit_code == 0, f"CLI failed: {result.output}\n{result.exception}"
        assert "LIVE SURGERY" in result.output
        assert "test topic" in result.output
        assert "Phase 1: Independent Analysis" in result.output
        assert "Phase 2: Cross-Review" in result.output
        assert "Phase 3: Open Exploration" in result.output
        assert "Phase 4: Synthesis" in result.output
        assert "CONSENSUS" in result.output

        # Verify phase methods were called
        mock_team.phase_start.assert_called_once()
        mock_team.phase_deepen.assert_called_once()
        mock_team.phase_explore.assert_called_once()
        mock_team.phase_synthesize.assert_called_once()

        # Verify session cleanup
        mock_sessions.delete.assert_called_once_with("test-123")

    @patch("three_surgeons.cli.main.create_backend_from_config")
    @patch("three_surgeons.cli.main._make_neuro")
    @patch("three_surgeons.cli.main.EvidenceStore")
    @patch("three_surgeons.cli.main.LLMProvider")
    @patch("three_surgeons.core.cross_exam.SurgeryTeam")
    def test_without_live_uses_iterative(
        self,
        mock_team_cls,
        mock_llm,
        mock_evidence,
        mock_neuro,
        mock_backend,
    ) -> None:
        """Without --live, cross_examine_iterative should be called."""
        mock_team = MagicMock()
        mock_result = MagicMock()
        mock_result.warnings = []
        mock_result.cardiologist_report = "cardio report"
        mock_result.neurologist_report = "neuro report"
        mock_result.cardiologist_exploration = None
        mock_result.neurologist_exploration = None
        mock_result.synthesis = "synthesis"
        mock_result.iteration_count = 1
        mock_result.escalation_needed = False
        mock_result.total_cost = 0.01
        mock_result.total_latency_ms = 500
        mock_team.cross_examine_iterative.return_value = mock_result
        mock_team_cls.return_value = mock_team

        runner = CliRunner()
        mock_config = MagicMock()
        mock_config.review.depth = "single"

        result = runner.invoke(
            cli,
            ["cross-exam", "test topic"],
            obj={"config": mock_config},
        )

        assert result.exit_code == 0, f"CLI failed: {result.output}\n{result.exception}"
        mock_team.cross_examine_iterative.assert_called_once()
        # phase methods should NOT be called
        mock_team.phase_start.assert_not_called()

    def test_dry_run_takes_precedence_over_live(self) -> None:
        """--dry-run should still work even when --live is also passed."""
        runner = CliRunner()
        with patch("three_surgeons.core.dry_run.check_dry_run") as mock_dry:
            mock_dry.return_value = MagicMock(
                to_dict=lambda: {"status": "dry_run", "action": "cross_examine"}
            )
            mock_config = MagicMock()
            result = runner.invoke(
                cli,
                ["cross-exam", "--live", "--dry-run", "test topic"],
                obj={"config": mock_config},
            )

        assert result.exit_code == 0
        assert "dry_run" in result.output
        mock_dry.assert_called_once()
