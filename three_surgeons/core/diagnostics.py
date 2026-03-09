"""Structured diagnostic checks with 3S-* error codes."""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Optional


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
