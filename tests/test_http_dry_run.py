"""Test HTTP dry-run via X-Dry-Run header."""
import pytest
from starlette.testclient import TestClient
from three_surgeons.http.server import create_app


@pytest.fixture
def client():
    app = create_app()
    return TestClient(app)


def test_dry_run_header(client):
    resp = client.post(
        "/tool/cross_examine",
        json={"topic": "test"},
        headers={"X-Dry-Run": "true"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data.get("dry_run") is True
    assert "estimated_cost_usd" in data


def test_no_dry_run_without_header(client):
    # Without header, tool would actually execute (may fail without LLM)
    # Just verify the header is not present in normal flow
    resp = client.post("/tool/probe", json={})
    data = resp.json()
    assert data.get("dry_run") is not True
