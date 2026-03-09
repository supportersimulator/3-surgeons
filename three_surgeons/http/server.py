"""Layer 2 REST server — Starlette ASGI app exposing 3-Surgeon tools over HTTP.

Thin bridge between IDE adapters (VS Code, Cursor) and the same core functions
used by the MCP server.  Run: 3s serve  (or: python -m three_surgeons.http)

4 base tools exposed (3-surgeon consensus — sentinel/gates are internal):
  POST /tool/probe          — health-check all 3 surgeons
  POST /tool/cross_examine  — full cross-examination
  POST /tool/consult        — quick consult
  POST /tool/consensus      — confidence-weighted consensus

  GET  /health              — server health + tool list
  GET  /tools               — dynamic tool discovery
"""
from __future__ import annotations

import json
import logging
from typing import Any, Callable

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

import three_surgeons.mcp.server as _mcp

logger = logging.getLogger(__name__)

# ── Tool registry (4 base tools — sentinel is internal) ─────────────────

ToolSpec = dict[str, Any]

BASE_TOOLS: dict[str, ToolSpec] = {
    "probe": {
        "fn_name": "_probe",
        "description": "Health check all 3 surgeons",
        "params": {},
    },
    "cross_examine": {
        "fn_name": "_cross_examine",
        "description": "Full cross-examination protocol with iterative review",
        "params": {
            "topic": {"type": "string", "required": True},
            "depth": {"type": "string", "required": False, "default": "full"},
            "mode": {"type": "string", "required": False, "default": "single"},
        },
    },
    "consult": {
        "fn_name": "_consult",
        "description": "Quick consult with both surgeons",
        "params": {
            "topic": {"type": "string", "required": True},
        },
    },
    "consensus": {
        "fn_name": "_consensus",
        "description": "Confidence-weighted consensus on a claim",
        "params": {
            "claim": {"type": "string", "required": True},
        },
    },
}


def _resolve_fn(tool_spec: ToolSpec) -> Callable:
    """Resolve tool function from mcp.server module at call time."""
    return getattr(_mcp, tool_spec["fn_name"])


def _validate_params(tool_spec: ToolSpec, body: dict) -> dict[str, Any]:
    """Extract and validate params from request body against tool spec.

    Returns kwargs dict for the tool function.
    Raises ValueError on missing required params.
    """
    params_spec = tool_spec["params"]
    kwargs: dict[str, Any] = {}

    for name, spec in params_spec.items():
        if name in body:
            kwargs[name] = body[name]
        elif spec.get("required", False):
            raise ValueError(f"Missing required parameter: {name}")
        elif "default" in spec:
            kwargs[name] = spec["default"]

    return kwargs


# ── Route handlers ───────────────────────────────────────────────────────


async def health(request: Request) -> JSONResponse:
    """GET /health — server health + available tool list."""
    return JSONResponse({
        "status": "ok",
        "tools": list(BASE_TOOLS.keys()),
    })


async def tools(request: Request) -> JSONResponse:
    """GET /tools — dynamic tool discovery with param schemas."""
    tool_list = []
    for name, spec in BASE_TOOLS.items():
        tool_list.append({
            "name": name,
            "description": spec["description"],
            "params": spec["params"],
        })
    return JSONResponse({"tools": tool_list})


async def invoke_tool(request: Request) -> JSONResponse:
    """POST /tool/{name} — invoke a 3-surgeon tool by name."""
    name = request.path_params["name"]

    if name not in BASE_TOOLS:
        return JSONResponse(
            {"error": f"Unknown tool: {name}", "available": list(BASE_TOOLS.keys())},
            status_code=404,
        )

    tool_spec = BASE_TOOLS[name]
    fn: Callable = _resolve_fn(tool_spec)

    # Parse body (empty body OK for no-param tools like probe)
    try:
        if await request.body():
            body = await request.json()
        else:
            body = {}
    except json.JSONDecodeError:
        return JSONResponse(
            {"error": "Invalid JSON in request body"},
            status_code=400,
        )

    # Validate params
    try:
        kwargs = _validate_params(tool_spec, body)
    except ValueError as exc:
        return JSONResponse(
            {"error": str(exc)},
            status_code=400,
        )

    # Invoke tool
    try:
        result = fn(**kwargs)
        return JSONResponse(result)
    except Exception as exc:
        logger.error("Tool %s failed: %s", name, exc, exc_info=True)
        return JSONResponse(
            {"error": f"Tool execution failed: {type(exc).__name__}: {exc}"},
            status_code=500,
        )


# ── App assembly ─────────────────────────────────────────────────────────

def create_app() -> Starlette:
    """Factory for the REST app — used by Task 9 (MCP + REST unified server)."""
    app = Starlette(routes=[
        Route("/health", health, methods=["GET"]),
        Route("/tools", tools, methods=["GET"]),
        Route("/tool/{name}", invoke_tool, methods=["POST"]),
    ])

    # Mount MCP server if SDK available
    try:
        from three_surgeons.mcp.server import create_server
        mcp_server = create_server()
        if mcp_server is not None:
            mcp_asgi = mcp_server.sse_app()
            app.mount("/mcp", mcp_asgi)
            logger.info("MCP server mounted at /mcp")
    except Exception as exc:
        logger.info("MCP not mounted: %s", exc)

    return app
