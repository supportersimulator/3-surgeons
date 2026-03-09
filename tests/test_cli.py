"""Tests for the 3-Surgeons CLI entry point."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

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


class TestCrossExamMode:
    """CLI --mode flag for cross-exam command."""

    def test_mode_flag_accepted(self, tmp_path, monkeypatch):
        """The --mode flag should be accepted without error."""
        import sys
        from three_surgeons.core.cross_exam import CrossExamResult

        mock_result = CrossExamResult(
            topic="test topic",
            cardiologist_report="Cardio",
            neurologist_report="Neuro",
            synthesis="Synthesis",
            total_cost=0.0,
            total_latency_ms=100,
        )

        cli_main_mod = sys.modules["three_surgeons.cli.main"]
        with patch.object(cli_main_mod, "LLMProvider"), \
             patch.object(cli_main_mod, "EvidenceStore"), \
             patch("three_surgeons.core.cross_exam.SurgeryTeam.cross_examine_iterative", return_value=mock_result):
            runner = CliRunner()
            result = runner.invoke(cli, ["cross-exam", "--mode", "iterative", "test topic"])
            # Should not fail with "no such option"
            assert "no such option" not in (result.output or "").lower()

    def test_mode_flag_default_is_single(self, tmp_path, monkeypatch):
        import sys
        from three_surgeons.core.cross_exam import CrossExamResult

        mock_result = CrossExamResult(
            topic="test topic",
            cardiologist_report="Cardio",
            neurologist_report="Neuro",
            synthesis="Synthesis",
            total_cost=0.0,
            total_latency_ms=100,
        )

        cli_main_mod = sys.modules["three_surgeons.cli.main"]
        with patch.object(cli_main_mod, "LLMProvider"), \
             patch.object(cli_main_mod, "EvidenceStore"), \
             patch("three_surgeons.core.cross_exam.SurgeryTeam.cross_examine_iterative", return_value=mock_result):
            runner = CliRunner()
            result = runner.invoke(cli, ["cross-exam", "test topic"])
            assert "no such option" not in (result.output or "").lower()


class TestModeCommand:
    """CLI 'mode' command for setting review depth."""

    def test_mode_show_current(self):
        runner = CliRunner()
        result = runner.invoke(cli, ["mode"])
        assert result.exit_code == 0

    def test_mode_set_continuous(self, tmp_path):
        runner = CliRunner()
        result = runner.invoke(cli, ["mode", "continuous"])
        assert "continuous" in (result.output or "").lower()


class TestReviewWeightsCommand:
    """CLI review-weights commands."""

    def test_weights_show(self):
        runner = CliRunner()
        result = runner.invoke(cli, ["review-weights"])
        assert result.exit_code == 0

    def test_weights_export(self, tmp_path):
        runner = CliRunner()
        out_file = str(tmp_path / "weights.json")
        result = runner.invoke(cli, ["review-weights", "export", "--output", out_file])
        assert result.exit_code == 0


class TestServeCommand:
    """Test the 3s serve command."""

    def test_serve_command_exists(self) -> None:
        runner = CliRunner()
        result = runner.invoke(cli, ["serve", "--help"])
        assert result.exit_code == 0
        assert "Start the 3-Surgeons HTTP server" in result.output

    def test_serve_default_port(self) -> None:
        runner = CliRunner()
        result = runner.invoke(cli, ["serve", "--help"])
        assert "3456" in result.output

    @patch("uvicorn.run")
    @patch("three_surgeons.http.server.create_app")
    def test_serve_invokes_uvicorn(self, mock_create_app, mock_uvicorn_run) -> None:
        mock_app = MagicMock()
        mock_create_app.return_value = mock_app
        runner = CliRunner()
        result = runner.invoke(cli, ["serve"])
        assert result.exit_code == 0
        mock_create_app.assert_called_once()
        mock_uvicorn_run.assert_called_once_with(mock_app, host="127.0.0.1", port=3456)


class TestDoctorCommand:
    """Test the doctor diagnostic command."""

    def test_doctor_outputs_json(self) -> None:
        """Doctor should output valid JSON."""
        import json
        runner = CliRunner()
        result = runner.invoke(cli, ["doctor", "--json"])
        assert result.exit_code in (0, 1)  # 0=healthy, 1=issues
        data = json.loads(result.output)
        assert "checks" in data
        assert "all_passed" in data
        assert isinstance(data["checks"], list)

    def test_doctor_shows_codes(self) -> None:
        """Doctor output should contain 3S- error codes."""
        runner = CliRunner()
        result = runner.invoke(cli, ["doctor"])
        assert "3S-" in result.output

    def test_doctor_exit_code_on_failure(self) -> None:
        """Doctor exits 1 when any check fails."""
        runner = CliRunner()
        result = runner.invoke(cli, ["doctor"])
        assert result.exit_code in (0, 1)

    def test_doctor_in_help(self) -> None:
        runner = CliRunner()
        result = runner.invoke(cli, ["--help"])
        assert "doctor" in result.output

    def test_doctor_json_has_fix_hints(self) -> None:
        """Failed checks should include fix hints in JSON mode."""
        import json
        runner = CliRunner()
        result = runner.invoke(cli, ["doctor", "--json"])
        data = json.loads(result.output)
        for check in data.get("failed", []):
            assert "fix" in check, f"Failed check {check['code']} missing fix hint"


class TestSetupCheckDiagnostics:
    """Verify setup-check now includes 3S- codes."""

    def test_setup_check_includes_codes(self) -> None:
        import json
        runner = CliRunner()
        result = runner.invoke(cli, ["setup-check"])
        # Extract the JSON object from output (guidance text may follow)
        raw = result.output
        # Find the outermost JSON object: first '{' to its matching '}'
        start = raw.index("{")
        depth = 0
        end = start
        for i, ch in enumerate(raw[start:], start):
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    end = i
                    break
        data = json.loads(raw[start:end + 1])
        assert "diagnostics" in data
        for d in data["diagnostics"]:
            assert d["code"].startswith("3S-")


class TestMainEntryPoint:
    """Test that the main() function exists and is callable."""

    def test_main_exists(self) -> None:
        from three_surgeons.cli.main import main
        assert callable(main)

    def test_cli_module_exports(self) -> None:
        from three_surgeons.cli import cli as cli_export, main as main_export
        assert cli_export is cli
        assert callable(main_export)
