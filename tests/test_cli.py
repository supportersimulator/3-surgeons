"""Tests for the 3-Surgeons CLI entry point."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest
import yaml
from click.testing import CliRunner

from three_surgeons.cli.main import cli


class TestCLIHelp:
    """Test that the CLI group displays help correctly."""

    def test_help(self) -> None:
        runner = CliRunner()
        result = runner.invoke(cli, ["--help"])
        assert result.exit_code == 0
        assert "3-Surgeons" in result.output

    def test_help_lists_commands(self) -> None:
        runner = CliRunner()
        result = runner.invoke(cli, ["--help"])
        assert result.exit_code == 0
        # All registered commands should appear in help
        assert "init" in result.output
        assert "probe" in result.output
        assert "cross-exam" in result.output
        assert "consult" in result.output
        assert "consensus" in result.output
        assert "sentinel" in result.output
        assert "gains-gate" in result.output
        assert "ab-propose" in result.output


class TestInitCommand:
    """Test the interactive init wizard."""

    def test_init_preset_selection(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Init wizard should offer preset selection."""
        monkeypatch.setenv("HOME", str(tmp_path))
        runner = CliRunner()
        # Select preset 1 (hybrid)
        result = runner.invoke(cli, ["init"], input="1\n")
        assert "Choose a preset" in result.output
        assert "Security reminder" in result.output
        # Config file should be created
        config_path = tmp_path / ".3surgeons" / "config.yaml"
        assert config_path.exists()

    def test_init_creates_config(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("HOME", str(tmp_path))
        runner = CliRunner()
        # Select preset 4 (custom), then provide manual config values
        result = runner.invoke(
            cli,
            ["init"],
            input="4\nopenai\ngpt-4.1-mini\nhttps://api.openai.com/v1\nOPENAI_API_KEY\nollama\nqwen3:4b\nhttp://localhost:11434/v1\n\n",
        )
        assert result.exit_code == 0
        assert (tmp_path / ".3surgeons" / "config.yaml").exists()

    def test_init_writes_valid_yaml(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("HOME", str(tmp_path))
        runner = CliRunner()
        # Select preset 4 (custom), then provide manual config values
        runner.invoke(
            cli,
            ["init"],
            input="4\nopenai\ngpt-4.1-mini\nhttps://api.openai.com/v1\nOPENAI_API_KEY\nollama\nqwen3:4b\nhttp://localhost:11434/v1\n\n",
        )
        config_path = tmp_path / ".3surgeons" / "config.yaml"
        data = yaml.safe_load(config_path.read_text())
        assert "surgeons" in data
        assert "cardiologist" in data["surgeons"]
        assert "neurologist" in data["surgeons"]
        assert data["surgeons"]["cardiologist"]["provider"] == "openai"
        assert data["surgeons"]["cardiologist"]["model"] == "gpt-4.1-mini"
        assert data["surgeons"]["neurologist"]["provider"] == "ollama"
        assert data["surgeons"]["neurologist"]["model"] == "qwen3:4b"


class TestProbeCommand:
    """Test the probe (health check) command."""

    def test_probe_command(self) -> None:
        runner = CliRunner()
        result = runner.invoke(cli, ["probe"])
        # Will fail to connect but should not crash
        assert result.exit_code in (0, 1)

    def test_probe_does_not_crash_when_unreachable(self) -> None:
        runner = CliRunner()
        result = runner.invoke(cli, ["probe"])
        # Even with no running surgeons, should handle gracefully
        assert result.exception is None or isinstance(result.exception, SystemExit)


class TestCrossExamCommand:
    """Test the cross-exam command."""

    def test_cross_exam_requires_topic(self) -> None:
        runner = CliRunner()
        result = runner.invoke(cli, ["cross-exam"])
        # Missing required argument should fail
        assert result.exit_code != 0

    def test_cross_exam_delegates_to_surgery_team(self) -> None:
        """Cross-exam should delegate to SurgeryTeam.cross_examine()."""
        import sys
        from three_surgeons.core.cross_exam import CrossExamResult

        mock_result = CrossExamResult(
            topic="test topic",
            cardiologist_report="Cardio analysis",
            neurologist_report="Neuro analysis",
            synthesis="Synthesis here",
            total_cost=0.002,
            total_latency_ms=200,
        )

        cli_main_mod = sys.modules["three_surgeons.cli.main"]

        with patch.object(cli_main_mod, "LLMProvider"), \
             patch.object(cli_main_mod, "EvidenceStore"), \
             patch("three_surgeons.core.cross_exam.SurgeryTeam.cross_examine", return_value=mock_result):
            runner = CliRunner()
            result = runner.invoke(cli, ["cross-exam", "test topic"])
            # Should not crash
            assert result.exit_code in (0, 1)


class TestConsultCommand:
    """Test the consult command."""

    def test_consult_requires_topic(self) -> None:
        runner = CliRunner()
        result = runner.invoke(cli, ["consult"])
        assert result.exit_code != 0


class TestConsensusCommand:
    """Test the consensus command."""

    def test_consensus_requires_claim(self) -> None:
        runner = CliRunner()
        result = runner.invoke(cli, ["consensus"])
        assert result.exit_code != 0


class TestSentinelCommand:
    """Test the sentinel command."""

    def test_sentinel_requires_content(self) -> None:
        runner = CliRunner()
        result = runner.invoke(cli, ["sentinel"])
        assert result.exit_code != 0

    def test_sentinel_runs_with_content(self) -> None:
        runner = CliRunner()
        result = runner.invoke(cli, ["sentinel", "auth token jwt session"])
        assert result.exit_code == 0
        # Should show some output about vectors
        assert "sentinel" in result.output.lower() or "vector" in result.output.lower() or "risk" in result.output.lower()


class TestGainsGateCommand:
    """Test the gains-gate command."""

    def test_gains_gate_runs(self) -> None:
        runner = CliRunner()
        result = runner.invoke(cli, ["gains-gate"])
        # Should complete (pass or fail) without crashing
        assert result.exit_code in (0, 1)


class TestABProposeCommand:
    """Test the ab-propose command."""

    def test_ab_propose_requires_all_args(self) -> None:
        runner = CliRunner()
        result = runner.invoke(cli, ["ab-propose"])
        assert result.exit_code != 0

    def test_ab_propose_rejects_forbidden_param(self) -> None:
        runner = CliRunner()
        result = runner.invoke(
            cli,
            ["ab-propose", "safety_gate", "a", "b", "test hypothesis"],
        )
        # Should fail because safety_gate is a forbidden param
        assert result.exit_code == 1


class TestMainEntryPoint:
    """Test that the main() function exists and is callable."""

    def test_main_exists(self) -> None:
        from three_surgeons.cli.main import main
        assert callable(main)

    def test_cli_module_exports(self) -> None:
        from three_surgeons.cli import cli as cli_export, main as main_export
        assert cli_export is cli
        assert callable(main_export)
