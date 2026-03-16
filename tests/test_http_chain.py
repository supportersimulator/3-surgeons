"""Tests for chain HTTP endpoints."""
from __future__ import annotations

from unittest.mock import patch, MagicMock

import pytest
from starlette.testclient import TestClient

from three_surgeons.http.server import create_app


@pytest.fixture
def client():
    app = create_app()
    return TestClient(app)


def test_chain_presets_in_tool_list(client):
    resp = client.get("/health")
    assert resp.status_code == 200
    tools = resp.json()["tools"]
    assert "cap_chain_presets" in tools


def test_chain_presets_endpoint(client):
    resp = client.post("/tool/cap_chain_presets")
    assert resp.status_code == 200
    data = resp.json()
    assert "presets" in data
    assert "full-3s" in data["presets"]


def test_chain_suggest_endpoint(client):
    resp = client.post("/tool/cap_chain_suggest", json={"trigger": ""})
    assert resp.status_code == 200
    data = resp.json()
    assert "suggestion" in data
