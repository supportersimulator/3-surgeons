"""Integration test — verify all 35 tools are wired in HTTP bridge."""
import pytest
from three_surgeons.http.server import BASE_TOOLS, create_app
from three_surgeons.http.schemas import TOOL_SCHEMAS


EXPECTED_TOOL_COUNT = 35


def test_all_tools_registered():
    """Every tool in BASE_TOOLS has a valid fn_name."""
    assert len(BASE_TOOLS) >= EXPECTED_TOOL_COUNT, (
        f"Expected {EXPECTED_TOOL_COUNT}+ tools, got {len(BASE_TOOLS)}"
    )


def test_all_tools_resolvable():
    """Every fn_name in BASE_TOOLS resolves to an actual function."""
    import three_surgeons.mcp.server as _mcp
    for name, spec in BASE_TOOLS.items():
        fn = getattr(_mcp, spec["fn_name"], None)
        assert fn is not None, f"Tool {name} fn_name={spec['fn_name']} not found in mcp.server"
        assert callable(fn), f"Tool {name} fn_name={spec['fn_name']} is not callable"


def test_schema_coverage():
    """Tools that accept parameters should have a schema."""
    # These tools take no params (probe-like)
    no_param_tools = {"probe", "cap_status", "cap_research_status", "cap_ab_queue",
                      "upgrade_probe", "upgrade_history", "neurologist_pulse_tool",
                      "introspect_tool"}
    for name in BASE_TOOLS:
        if name not in no_param_tools:
            assert name in TOOL_SCHEMAS, f"Tool {name} missing from TOOL_SCHEMAS"


def test_health_endpoint():
    """Health endpoint returns all tools."""
    from starlette.testclient import TestClient
    app = create_app()
    client = TestClient(app)
    resp = client.get("/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data["tool_count"] >= EXPECTED_TOOL_COUNT


def test_dry_run_header():
    """X-Dry-Run header returns plan without executing."""
    from starlette.testclient import TestClient
    app = create_app()
    client = TestClient(app)
    resp = client.post("/tool/probe", headers={"X-Dry-Run": "true"})
    assert resp.status_code == 200
    data = resp.json()
    assert data.get("dry_run") is True
