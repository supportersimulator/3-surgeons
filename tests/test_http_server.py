"""Tests for the Layer 2 HTTP REST server.

Validates:
- GET /health returns status and tool list
- GET /tools returns dynamic tool discovery (4 base tools, no sentinel)
- POST /tool/{name} invokes tools with correct params
- Error handling: 404 unknown tool, 400 invalid params, 500 tool errors
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from starlette.testclient import TestClient


@pytest.fixture()
def client():
    """Create a fresh test client per test (no shared state)."""
    from three_surgeons.http.server import create_app

    return TestClient(create_app())


# ── Health endpoint ──────────────────────────────────────────────────────


class TestHealth:
    """GET /health returns server status and tool list."""

    def test_health_returns_ok(self, client):
        resp = client.get("/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"

    def test_health_lists_tools(self, client):
        resp = client.get("/health")
        data = resp.json()
        assert isinstance(data["tools"], list)
        assert set(data["tools"]) == {"probe", "cross_examine", "consult", "consensus"}

    def test_health_lists_exactly_4_tools(self, client):
        resp = client.get("/health")
        data = resp.json()
        assert len(data["tools"]) == 4


# ── Tool discovery ───────────────────────────────────────────────────────


class TestToolDiscovery:
    """GET /tools returns dynamic tool schemas."""

    def test_tools_lists_base_4(self, client):
        resp = client.get("/tools")
        assert resp.status_code == 200
        data = resp.json()
        names = {t["name"] for t in data["tools"]}
        assert names == {"probe", "cross_examine", "consult", "consensus"}

    def test_tools_does_not_list_sentinel(self, client):
        """sentinel_run is internal-only per 3-surgeon consensus."""
        resp = client.get("/tools")
        data = resp.json()
        names = {t["name"] for t in data["tools"]}
        assert "sentinel_run" not in names

    def test_tools_include_descriptions(self, client):
        resp = client.get("/tools")
        data = resp.json()
        for tool in data["tools"]:
            assert "description" in tool
            assert len(tool["description"]) > 0

    def test_tools_include_param_schemas(self, client):
        resp = client.get("/tools")
        data = resp.json()
        for tool in data["tools"]:
            assert "params" in tool

    def test_cross_examine_has_topic_param(self, client):
        resp = client.get("/tools")
        data = resp.json()
        xe = next(t for t in data["tools"] if t["name"] == "cross_examine")
        assert "topic" in xe["params"]

    def test_probe_has_no_params(self, client):
        resp = client.get("/tools")
        data = resp.json()
        probe = next(t for t in data["tools"] if t["name"] == "probe")
        assert probe["params"] == {}


# ── Tool invocation ──────────────────────────────────────────────────────


class TestToolInvocation:
    """POST /tool/{name} invokes tools correctly."""

    @patch("three_surgeons.mcp.server._probe")
    def test_probe_invocation(self, mock_probe, client):
        mock_probe.return_value = {
            "atlas": {"status": "ok"},
            "cardiologist": {"status": "ok", "latency_ms": 42},
            "neurologist": {"status": "ok", "latency_ms": 55},
        }
        resp = client.post("/tool/probe")
        assert resp.status_code == 200
        data = resp.json()
        assert data["atlas"]["status"] == "ok"
        mock_probe.assert_called_once_with()

    @patch("three_surgeons.mcp.server._cross_examine")
    def test_cross_examine_passes_params(self, mock_xe, client):
        mock_xe.return_value = {"topic": "test", "synthesis": "agreed"}
        resp = client.post(
            "/tool/cross_examine",
            json={"topic": "test topic", "depth": "quick", "mode": "iterative"},
        )
        assert resp.status_code == 200
        mock_xe.assert_called_once_with(
            topic="test topic", depth="quick", mode="iterative",
        )

    @patch("three_surgeons.mcp.server._cross_examine")
    def test_cross_examine_uses_defaults(self, mock_xe, client):
        mock_xe.return_value = {"topic": "test", "synthesis": "agreed"}
        resp = client.post(
            "/tool/cross_examine",
            json={"topic": "test topic"},
        )
        assert resp.status_code == 200
        mock_xe.assert_called_once_with(
            topic="test topic", depth="full", mode="single",
        )

    @patch("three_surgeons.mcp.server._consult")
    def test_consult_invocation(self, mock_consult, client):
        mock_consult.return_value = {"topic": "design", "cardiologist_report": "ok"}
        resp = client.post("/tool/consult", json={"topic": "design"})
        assert resp.status_code == 200
        assert resp.json()["topic"] == "design"
        mock_consult.assert_called_once_with(topic="design")

    @patch("three_surgeons.mcp.server._consensus")
    def test_consensus_invocation(self, mock_consensus, client):
        mock_consensus.return_value = {"claim": "X is true", "weighted_score": 0.8}
        resp = client.post("/tool/consensus", json={"claim": "X is true"})
        assert resp.status_code == 200
        assert resp.json()["weighted_score"] == 0.8
        mock_consensus.assert_called_once_with(claim="X is true")


# ── Error handling ───────────────────────────────────────────────────────


class TestErrorHandling:
    """HTTP error codes for bad requests and tool failures."""

    def test_unknown_tool_returns_404(self, client):
        resp = client.post("/tool/nonexistent", json={})
        assert resp.status_code == 404
        data = resp.json()
        assert "error" in data
        assert "nonexistent" in data["error"]

    def test_missing_required_param_returns_422(self, client):
        resp = client.post("/tool/cross_examine", json={})
        assert resp.status_code == 422
        data = resp.json()
        assert "error" in data

    def test_invalid_json_returns_400(self, client):
        resp = client.post(
            "/tool/cross_examine",
            content=b"not json",
            headers={"content-type": "application/json"},
        )
        assert resp.status_code == 400
        assert "error" in resp.json()

    @patch("three_surgeons.mcp.server._probe")
    def test_tool_exception_returns_500(self, mock_probe, client):
        mock_probe.side_effect = RuntimeError("LLM connection failed")
        resp = client.post("/tool/probe")
        assert resp.status_code == 500
        data = resp.json()
        assert "error" in data
        assert "RuntimeError" in data["error"]
        # Internal message should NOT leak
        assert "LLM connection failed" not in data["error"]

    @patch("three_surgeons.mcp.server._probe")
    def test_500_does_not_leak_internal_details(self, mock_probe, client):
        mock_probe.side_effect = RuntimeError("secret DB password in traceback")
        resp = client.post("/tool/probe")
        assert resp.status_code == 500
        data = resp.json()
        assert "error" in data
        assert "secret DB password" not in data["error"]
        assert "Tool execution failed" in data["error"]

    @patch("three_surgeons.mcp.server._consult")
    def test_tool_error_includes_type(self, mock_consult, client):
        mock_consult.side_effect = TimeoutError("GPU lock timeout")
        resp = client.post("/tool/consult", json={"topic": "test"})
        assert resp.status_code == 500
        assert "TimeoutError" in resp.json()["error"]

    def test_sentinel_not_accessible_via_http(self, client):
        """sentinel_run should not be invocable via the REST API."""
        resp = client.post("/tool/sentinel_run", json={"content": "test"})
        assert resp.status_code == 404


# ── Rate limiting ────────────────────────────────────────────────────────


class TestRateLimiting:
    """Basic rate limiting on tool invocation."""

    @patch("three_surgeons.mcp.server._probe")
    def test_rate_limit_returns_429_after_burst(self, mock_probe, client):
        """Rapid-fire calls should eventually get throttled."""
        mock_probe.return_value = {"atlas": {"status": "ok"}}
        responses = []
        for _ in range(25):
            resp = client.post("/tool/probe")
            responses.append(resp.status_code)
        assert 429 in responses

    @patch("three_surgeons.mcp.server._probe")
    def test_rate_limit_includes_retry_after(self, mock_probe, client):
        """429 response should include retry guidance."""
        mock_probe.return_value = {"atlas": {"status": "ok"}}
        for _ in range(25):
            resp = client.post("/tool/probe")
            if resp.status_code == 429:
                data = resp.json()
                assert "error" in data
                assert "rate" in data["error"].lower()
                break
        else:
            pytest.fail("Expected 429 rate limit response within 25 requests")


# ── CORS ──────────────────────────────────────────────────────────────────


class TestCORS:
    """CORS headers present on responses."""

    def test_health_has_cors_headers(self, client):
        resp = client.get("/health", headers={"Origin": "http://localhost:3000"})
        assert "access-control-allow-origin" in resp.headers

    def test_preflight_returns_200(self, client):
        resp = client.options(
            "/tool/probe",
            headers={
                "Origin": "http://localhost:3000",
                "Access-Control-Request-Method": "POST",
            },
        )
        assert resp.status_code == 200
        assert "access-control-allow-origin" in resp.headers


# ── MCP mount ────────────────────────────────────────────────────────────


class TestMCPMount:
    """MCP server mounts alongside REST when mcp SDK is available."""

    def test_mcp_mount_does_not_break_rest(self, client):
        """REST endpoints still work regardless of MCP mount status."""
        resp = client.get("/health")
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"

    def test_create_app_succeeds_without_mcp(self):
        """create_app() works even if mcp SDK is not installed."""
        from three_surgeons.http.server import create_app
        app = create_app()
        assert app is not None


# ── Auth attribution ────────────────────────────────────────────────────


class TestAuthAttribution:
    """X-User-Id and X-Session-Id headers are captured in audit entries."""

    @patch("three_surgeons.mcp.server._probe")
    def test_headers_passed_to_audit(self, mock_probe, client):
        """X-User-Id and X-Session-Id headers are captured."""
        mock_probe.return_value = {"atlas": {"status": "ok"}}
        resp = client.post(
            "/tool/probe",
            headers={"X-User-Id": "user_42", "X-Session-Id": "sess_abc"},
        )
        assert resp.status_code == 200
        # Verify audit entry has attribution
        trail = client.app.state.audit
        entries = trail.recent(limit=1)
        assert entries[0]["user_id"] == "user_42"
        assert entries[0]["session_id"] == "sess_abc"

    @patch("three_surgeons.mcp.server._probe")
    def test_missing_headers_default_to_anonymous(self, mock_probe, client):
        """Missing auth headers default to 'anonymous'/'unknown'."""
        mock_probe.return_value = {"atlas": {"status": "ok"}}
        resp = client.post("/tool/probe")
        assert resp.status_code == 200
        trail = client.app.state.audit
        entries = trail.recent(limit=1)
        assert entries[0]["user_id"] == "anonymous"
        assert entries[0]["session_id"] == "unknown"
