"""Integration tests: Layer 2 HTTP -> Layer 1 core (mocked LLM calls).

Tests the full HTTP stack end-to-end: request parsing, param validation,
tool resolution, core function invocation, and response serialization.
All LLM calls are mocked at the core layer boundary.
"""
from __future__ import annotations

from unittest.mock import patch

import pytest
from starlette.testclient import TestClient


@pytest.fixture()
def client():
    """Create a fresh test client per test."""
    from three_surgeons.http.server import create_app

    return TestClient(create_app())


class TestFullStackIntegration:
    """POST /tool/{name} -> core function -> result, with mocked LLM."""

    @patch("three_surgeons.mcp.server._probe")
    def test_probe_returns_surgeon_status(self, mock_probe, client):
        mock_probe.return_value = {
            "atlas": {"status": "ok"},
            "cardiologist": {"status": "ok", "latency_ms": 150},
            "neurologist": {"status": "ok", "latency_ms": 200},
        }
        resp = client.post("/tool/probe")
        assert resp.status_code == 200
        data = resp.json()
        assert "atlas" in data
        assert "cardiologist" in data
        assert "neurologist" in data
        assert data["atlas"]["status"] == "ok"

    @patch("three_surgeons.mcp.server._cross_examine")
    def test_cross_examine_full_flow(self, mock_xe, client):
        mock_xe.return_value = {
            "topic": "architecture",
            "rounds": 3,
            "synthesis": "All surgeons agree on microservices approach",
            "confidence": 0.92,
        }
        resp = client.post("/tool/cross_examine", json={
            "topic": "architecture",
            "depth": "full",
            "mode": "iterative",
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["topic"] == "architecture"
        assert data["confidence"] == 0.92
        mock_xe.assert_called_once_with(
            topic="architecture", depth="full", mode="iterative", file_paths=None,
        )

    @patch("three_surgeons.mcp.server._consult")
    def test_consult_returns_opinions(self, mock_consult, client):
        mock_consult.return_value = {
            "topic": "database choice",
            "cardiologist_report": "PostgreSQL recommended",
            "neurologist_report": "Agree with PostgreSQL",
        }
        resp = client.post("/tool/consult", json={"topic": "database choice"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["topic"] == "database choice"
        assert "cardiologist_report" in data
        mock_consult.assert_called_once_with(topic="database choice", file_paths=None)

    @patch("three_surgeons.mcp.server._consensus")
    def test_consensus_returns_weighted_score(self, mock_consensus, client):
        mock_consensus.return_value = {
            "claim": "Redis is appropriate here",
            "weighted_score": 0.85,
            "atlas_confidence": 0.9,
            "cardiologist_confidence": 0.8,
            "neurologist_confidence": 0.85,
        }
        resp = client.post("/tool/consensus", json={"claim": "Redis is appropriate here"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["weighted_score"] == 0.85
        assert data["claim"] == "Redis is appropriate here"

    def test_health_and_tool_discovery_consistent(self, client):
        """Health endpoint tool list matches tools endpoint names."""
        health_resp = client.get("/health")
        tools_resp = client.get("/tools")
        health_tools = set(health_resp.json()["tools"])
        tools_names = {t["name"] for t in tools_resp.json()["tools"]}
        assert health_tools == tools_names
