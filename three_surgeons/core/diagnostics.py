"""Structured diagnostic checks with 3S-* error codes."""
from __future__ import annotations

import sys
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Optional

from three_surgeons.core.config import detect_local_backend


class DiagnosticCode(Enum):
    """3S-{category}-{status} error codes.

    Categories: PY (python), MCP (mcp runtime), CFG (config),
    NET (network/endpoints), KEY (api keys), LOC (local backends).
    """

    # Python
    PY_OK = "3S-PY-OK"
    PY_OLD = "3S-PY-OLD"
    PY_NONE = "3S-PY-NONE"

    # MCP runtime
    MCP_OK = "3S-MCP-OK"
    MCP_MISSING = "3S-MCP-MISS"
    MCP_IMPORT = "3S-MCP-IMP"

    # Config
    CFG_OK = "3S-CFG-OK"
    CFG_DEFAULTS = "3S-CFG-DEF"
    CFG_PARSE = "3S-CFG-ERR"

    # Network / endpoints
    NET_OK = "3S-NET-OK"
    NET_UNREACHABLE = "3S-NET-DOWN"
    NET_TIMEOUT = "3S-NET-TMO"

    # API keys
    KEY_OK = "3S-KEY-OK"
    KEY_MISSING = "3S-KEY-MISS"

    # Local backends
    LOC_OK = "3S-LOC-OK"
    LOC_NONE = "3S-LOC-NONE"


@dataclass
class DiagnosticResult:
    """Single check result with optional fix hint."""

    code: DiagnosticCode
    passed: bool
    message: str
    fix: Optional[str] = None

    @classmethod
    def ok(cls, code: DiagnosticCode, message: str) -> DiagnosticResult:
        return cls(code=code, passed=True, message=message)

    @classmethod
    def fail(
        cls,
        code: DiagnosticCode,
        message: str,
        fix: Optional[str] = None,
    ) -> DiagnosticResult:
        return cls(code=code, passed=False, message=message, fix=fix)

    def to_dict(self) -> dict:
        d: dict = {
            "code": self.code.value,
            "passed": self.passed,
            "message": self.message,
        }
        if self.fix:
            d["fix"] = self.fix
        return d


def check_python_version() -> DiagnosticResult:
    """Check Python >= 3.10."""
    v = sys.version_info
    version_str = f"{v[0]}.{v[1]}.{v[2]}"
    if v >= (3, 10):
        return DiagnosticResult.ok(DiagnosticCode.PY_OK, f"Python {version_str}")
    return DiagnosticResult.fail(
        DiagnosticCode.PY_OLD,
        f"Python {version_str} < 3.10",
        fix="brew install python@3.12  # or: pyenv install 3.12",
    )


def check_mcp_importable() -> DiagnosticResult:
    """Check that mcp package is importable."""
    try:
        import mcp  # noqa: F401

        return DiagnosticResult.ok(DiagnosticCode.MCP_OK, "mcp package available")
    except ImportError:
        return DiagnosticResult.fail(
            DiagnosticCode.MCP_MISSING,
            "mcp package not installed",
            fix="pip install 'three-surgeons[mcp]'",
        )


def check_config() -> DiagnosticResult:
    """Check config file discovery."""
    project_path = Path.cwd() / ".3surgeons.yaml"
    home_path = Path.home() / ".3surgeons" / "config.yaml"
    if project_path.is_file():
        return DiagnosticResult.ok(DiagnosticCode.CFG_OK, f"Config: {project_path}")
    if home_path.is_file():
        return DiagnosticResult.ok(DiagnosticCode.CFG_OK, f"Config: {home_path}")
    return DiagnosticResult.fail(
        DiagnosticCode.CFG_DEFAULTS,
        "Using defaults (no config file found)",
        fix="Run: 3s init",
    )


def check_local_backends() -> DiagnosticResult:
    """Check for local LLM backends."""
    backends = detect_local_backend(timeout_s=2.0)
    if backends:
        names = ", ".join(b["provider"] for b in backends)
        return DiagnosticResult.ok(DiagnosticCode.LOC_OK, f"Found: {names}")
    return DiagnosticResult.fail(
        DiagnosticCode.LOC_NONE,
        "No local LLM backends detected",
        fix="Start Ollama, LM Studio, or mlx_lm.server",
    )


def run_all_checks() -> list[DiagnosticResult]:
    """Run all diagnostic checks, return list of results."""
    return [
        check_python_version(),
        check_mcp_importable(),
        check_config(),
        check_local_backends(),
    ]
