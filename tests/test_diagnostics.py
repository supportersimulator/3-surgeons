"""Tests for structured diagnostic error codes."""
from __future__ import annotations

from three_surgeons.core.diagnostics import DiagnosticCode, DiagnosticResult


class TestDiagnosticCodes:
    def test_code_format(self) -> None:
        """All codes follow 3S-XX-YYY pattern."""
        for code in DiagnosticCode:
            assert code.value.startswith("3S-"), f"{code.name} doesn't start with 3S-"
            parts = code.value.split("-")
            assert len(parts) == 3, f"{code.value} not 3-part"

    def test_result_ok(self) -> None:
        result = DiagnosticResult.ok(DiagnosticCode.PY_OK, "Python 3.12.0")
        assert result.passed is True
        assert result.code == DiagnosticCode.PY_OK

    def test_result_fail_has_fix(self) -> None:
        result = DiagnosticResult.fail(
            DiagnosticCode.PY_OLD,
            "Python 3.9.1 < 3.10",
            fix="brew install python@3.12",
        )
        assert result.passed is False
        assert result.fix == "brew install python@3.12"

    def test_result_to_dict(self) -> None:
        result = DiagnosticResult.ok(DiagnosticCode.PY_OK, "Python 3.12.0")
        d = result.to_dict()
        assert d["code"] == "3S-PY-OK"
        assert d["passed"] is True
        assert "fix" not in d


import sys
from unittest.mock import patch, MagicMock

from three_surgeons.core.diagnostics import (
    check_python_version,
    check_mcp_importable,
    check_config,
    check_local_backends,
)


class TestCheckPython:
    def test_python_310_passes(self) -> None:
        with patch.object(sys, "version_info", (3, 10, 0, "final", 0)):
            result = check_python_version()
            assert result.passed
            assert result.code == DiagnosticCode.PY_OK

    def test_python_39_fails(self) -> None:
        with patch.object(sys, "version_info", (3, 9, 1, "final", 0)):
            result = check_python_version()
            assert not result.passed
            assert result.code == DiagnosticCode.PY_OLD
            assert result.fix is not None


class TestCheckMCP:
    def test_mcp_importable(self) -> None:
        result = check_mcp_importable()
        assert result.code in (DiagnosticCode.MCP_OK, DiagnosticCode.MCP_MISSING)
        assert isinstance(result.passed, bool)


class TestCheckConfig:
    def test_no_config_returns_defaults(self, tmp_path, monkeypatch) -> None:
        monkeypatch.setenv("HOME", str(tmp_path))
        monkeypatch.chdir(tmp_path)
        result = check_config()
        assert result.code == DiagnosticCode.CFG_DEFAULTS

    def test_project_config_found(self, tmp_path, monkeypatch) -> None:
        monkeypatch.chdir(tmp_path)
        (tmp_path / ".3surgeons.yaml").write_text("surgeons:\n  cardiologist:\n    provider: openai\n")
        result = check_config()
        assert result.passed
        assert result.code == DiagnosticCode.CFG_OK


class TestCheckLocalBackends:
    def test_no_backends(self) -> None:
        with patch("three_surgeons.core.diagnostics.detect_local_backend", return_value=[]):
            result = check_local_backends()
            assert result.code == DiagnosticCode.LOC_NONE
            assert not result.passed

    def test_with_backends(self) -> None:
        fake = [{"provider": "ollama", "port": 11434, "models": ["llama3"]}]
        with patch("three_surgeons.core.diagnostics.detect_local_backend", return_value=fake):
            result = check_local_backends()
            assert result.code == DiagnosticCode.LOC_OK
            assert result.passed


from three_surgeons.core.diagnostics import run_all_checks


class TestRunAllChecks:
    def test_returns_list_of_results(self) -> None:
        results = run_all_checks()
        assert isinstance(results, list)
        assert len(results) >= 4  # python, mcp, config, backends
        for r in results:
            assert isinstance(r, DiagnosticResult)

    def test_to_json_structure(self) -> None:
        results = run_all_checks()
        output = {
            "checks": [r.to_dict() for r in results],
            "all_passed": all(r.passed for r in results),
            "failed": [r.to_dict() for r in results if not r.passed],
        }
        assert "checks" in output
        assert isinstance(output["all_passed"], bool)


class TestDoctorIntegration:
    """End-to-end: doctor JSON output matches contract from CI."""

    def test_full_contract(self) -> None:
        """Validates the exact contract CI checks for."""
        import json
        from click.testing import CliRunner
        from three_surgeons.cli.main import cli

        runner = CliRunner()
        result = runner.invoke(cli, ["doctor", "--json"])
        assert result.exit_code in (0, 1)

        data = json.loads(result.output)

        # Required top-level keys
        assert "checks" in data
        assert "all_passed" in data
        assert "failed" in data

        # All codes follow 3S- pattern
        for check in data["checks"]:
            assert check["code"].startswith("3S-"), f"Bad code: {check['code']}"
            assert isinstance(check["passed"], bool)
            assert "message" in check

        # Failed checks have fix hints
        for check in data["failed"]:
            assert "fix" in check, f"{check['code']} missing fix"

        # Consistency
        assert data["all_passed"] == (len(data["failed"]) == 0)
