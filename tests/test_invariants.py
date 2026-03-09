"""LazyGuard-inspired invariant tests — implementation-independent.

These tests define WHAT the 3-Surgeons plugin MUST guarantee,
not HOW it's implemented. Any refactor that breaks these breaks
the plugin's contract with its users.

Run: pytest tests/test_invariants.py -v
"""
import os
from pathlib import Path

import pytest


class TestSecurityInvariants:
    """No implementation detail knowledge — only observable behavior."""

    def test_path_traversal_never_leaks_data(self, tmp_path: Path):
        """INVARIANT: Paths outside base_dir produce zero content."""
        from three_surgeons.core.file_access import FileAccessPolicy, AccessOutcome
        policy = FileAccessPolicy(base_dirs=[str(tmp_path)])
        attack_paths = [
            "/etc/passwd",
            "/etc/shadow",
            str(tmp_path / ".." / ".." / "etc" / "passwd"),
            "../../../../etc/passwd",
            "/dev/null",
        ]
        for path in attack_paths:
            result = policy.check(path)
            assert result.outcome != AccessOutcome.AUTO_ACCEPT, \
                f"SECURITY VIOLATION: {path} was accepted"

    def test_sensitive_files_never_read(self, tmp_path: Path):
        """INVARIANT: .env, credentials, keys are never readable."""
        from three_surgeons.core.file_access import FileAccessPolicy, AccessOutcome
        policy = FileAccessPolicy(base_dirs=[str(tmp_path)])
        sensitive = [".env", "credentials.json", ".ssh/id_rsa"]
        for name in sensitive:
            p = tmp_path / name
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text("SECRET_KEY=abc123")
            result = policy.check(str(p))
            assert result.outcome != AccessOutcome.AUTO_ACCEPT, \
                f"SECURITY VIOLATION: {name} was readable"

    def test_content_budget_never_exceeded(self, tmp_path: Path):
        """INVARIANT: Total chars across all files <= budget."""
        from three_surgeons.core.file_access import (
            FileAccessPolicy, read_files_with_budget,
        )
        BUDGET = 50000
        policy = FileAccessPolicy(base_dirs=[str(tmp_path)])
        paths = []
        for i in range(50):
            f = tmp_path / f"file_{i}.py"
            f.write_text("x" * 10000)
            paths.append(str(f))
        result = read_files_with_budget(paths, policy, total_budget=BUDGET)
        total = sum(len(v) for v in result.values())
        assert total <= BUDGET, \
            f"BUDGET VIOLATION: {total} chars > {BUDGET} budget"


class TestCorrigibilityInvariants:
    """The 3-surgeon system must maintain epistemic integrity."""

    def test_cross_exam_always_has_exploration_phase(self):
        """INVARIANT: Cross-examination must include open exploration."""
        from unittest.mock import MagicMock
        from three_surgeons.core.cross_exam import SurgeryTeam
        from three_surgeons.core.models import LLMResponse
        from three_surgeons.core.state import MemoryBackend
        from three_surgeons.core.evidence import EvidenceStore
        import tempfile

        with tempfile.TemporaryDirectory() as td:
            cardio = MagicMock()
            cardio.query.return_value = LLMResponse(
                ok=True, content="Analysis", latency_ms=100, model="gpt-4.1-mini",
            )
            neuro = MagicMock()
            neuro.query.return_value = LLMResponse(
                ok=True, content="Analysis", latency_ms=50, model="qwen3:4b",
            )
            team = SurgeryTeam(
                cardiologist=cardio, neurologist=neuro,
                evidence=EvidenceStore(os.path.join(td, "ev.db")),
                state=MemoryBackend(),
            )
            result = team.cross_examine("test topic")
            # Phase 3 exploration MUST exist — the result has separate
            # cardiologist_exploration and neurologist_exploration fields.
            has_exploration = (
                result.cardiologist_exploration is not None
                or result.neurologist_exploration is not None
            )
            assert has_exploration, \
                "CORRIGIBILITY VIOLATION: No exploration phase in cross-exam"

    def test_audit_trail_records_every_invocation(self, tmp_path: Path):
        """INVARIANT: Every tool call produces an audit entry."""
        from three_surgeons.core.audit import AuditTrail
        trail = AuditTrail(storage_dir=str(tmp_path))
        for i in range(10):
            trail.record(tool=f"tool_{i}", params={}, status="success")
        entries = trail.recent(limit=100)
        assert len(entries) == 10, \
            "AUDIT VIOLATION: Not all invocations recorded"

    def test_rate_limiter_eventually_blocks(self):
        """INVARIANT: Rate limiter must enforce limits (not fail-open)."""
        from three_surgeons.http.rate_limit import MemoryRateLimiter
        rl = MemoryRateLimiter(max_calls=3, window_s=60.0)
        results = [rl.allow("test") for _ in range(10)]
        assert False in results, \
            "RATE LIMIT VIOLATION: Limiter never blocked"

    def test_pydantic_rejects_invalid_input(self):
        """INVARIANT: Invalid params produce 422, never reach tool function."""
        from pydantic import ValidationError
        from three_surgeons.http.schemas import CrossExamineRequest
        with pytest.raises(ValidationError):
            CrossExamineRequest(topic="", depth="invalid")


class TestHTTPInvariants:
    """REST API contract invariants."""

    def test_health_endpoint_always_returns_200(self):
        from starlette.testclient import TestClient
        from three_surgeons.http.server import create_app
        client = TestClient(create_app())
        resp = client.get("/health")
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"

    def test_unknown_tool_returns_404(self):
        from starlette.testclient import TestClient
        from three_surgeons.http.server import create_app
        client = TestClient(create_app())
        resp = client.post("/tool/nonexistent")
        assert resp.status_code == 404

    def test_tools_endpoint_lists_all_base_tools(self):
        from starlette.testclient import TestClient
        from three_surgeons.http.server import create_app
        client = TestClient(create_app())
        resp = client.get("/tools")
        names = {t["name"] for t in resp.json()["tools"]}
        assert {"probe", "cross_examine", "consult", "consensus"} <= names
