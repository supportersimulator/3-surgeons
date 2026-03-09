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
