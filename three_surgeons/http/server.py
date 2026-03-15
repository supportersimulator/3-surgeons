"""Layer 2 REST server — Starlette ASGI app exposing 3-Surgeon tools over HTTP.

Thin bridge between IDE adapters (VS Code, Cursor) and the same core functions
used by the MCP server.  Run: 3s serve  (or: python -m three_surgeons.http)

NOTE: All tool functions (_probe, _cross_examine, etc.) are SYNCHRONOUS.
Starlette runs them in a threadpool via async route handlers. LLM calls may
block for 10-120s — this is expected and handled by the VS Code adapter's
AbortSignal.timeout(120_000).

4 base tools exposed (3-surgeon consensus — sentinel/gates are internal):
  POST /tool/probe          — health-check all 3 surgeons
  POST /tool/cross_examine  — full cross-examination (may take 30-120s)
  POST /tool/consult        — quick consult (10-30s)
  POST /tool/consensus      — confidence-weighted consensus (10-30s)

  GET  /health              — server health + tool list
  GET  /tools               — dynamic tool discovery
"""
from __future__ import annotations

import json
import logging
import time as _time
from typing import Any, Callable

from pydantic import ValidationError
from starlette.applications import Starlette
from starlette.middleware.cors import CORSMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

import three_surgeons.mcp.server as _mcp
from three_surgeons.core.audit import AuditTrail
from three_surgeons.http.rate_limit import create_rate_limiter
from three_surgeons.http.schemas import TOOL_SCHEMAS

logger = logging.getLogger(__name__)

# ── Tool registry (4 base tools — sentinel is internal) ─────────────────

ToolSpec = dict[str, Any]

BASE_TOOLS: dict[str, ToolSpec] = {
    "probe": {
        "fn_name": "_probe",
        "description": "Health check all 3 surgeons",
    },
    "cross_examine": {
        "fn_name": "_cross_examine",
        "description": "Full cross-examination protocol with iterative review",
    },
    "consult": {
        "fn_name": "_consult",
        "description": "Quick consult with both surgeons",
    },
    "consensus": {
        "fn_name": "_consensus",
        "description": "Confidence-weighted consensus on a claim",
    },
    "cap_status": {
        "fn_name": "_cap_status",
        "description": "System health and capability overview",
    },
    "cap_research_status": {
        "fn_name": "_cap_research_status",
        "description": "Research budget and cost tracking",
    },
    "cap_ab_veto": {
        "fn_name": "_cap_ab_veto",
        "description": "Veto an A/B test",
    },
    "cap_ab_queue": {
        "fn_name": "_cap_ab_queue",
        "description": "List A/B tests in the queue",
    },
    "cap_ab_start": {
        "fn_name": "_cap_ab_start",
        "description": "Start an A/B test",
    },
    "cap_ab_measure": {
        "fn_name": "_cap_ab_measure",
        "description": "Measure an active A/B test",
    },
    "cap_ab_conclude": {
        "fn_name": "_cap_ab_conclude",
        "description": "Conclude an A/B test with verdict",
    },
    "cap_ab_collaborate": {
        "fn_name": "_cap_ab_collaborate",
        "description": "Multi-surgeon A/B test design",
    },
    "cap_research_evidence": {
        "fn_name": "_cap_research_evidence",
        "description": "Cross-check evidence with LLM analysis",
    },
    "cap_cardio_reverify": {
        "fn_name": "_cap_cardio_reverify",
        "description": "Multi-surgeon evidence reverification",
    },
    "cap_deep_audit": {
        "fn_name": "_cap_deep_audit",
        "description": "4-phase deep audit pipeline",
    },
}


def _resolve_fn(tool_spec: ToolSpec) -> Callable:
    """Resolve tool function from mcp.server module at call time."""
    return getattr(_mcp, tool_spec["fn_name"])


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
        schema_cls = TOOL_SCHEMAS.get(name)
        if schema_cls is not None:
            params = schema_cls.model_json_schema().get("properties", {})
        else:
            params = {}
        tool_list.append({
            "name": name,
            "description": spec["description"],
            "params": params,
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

    # Validate params via Pydantic
    schema = TOOL_SCHEMAS.get(name)
    if schema:
        try:
            validated = schema.model_validate(body)
            kwargs = validated.model_dump(exclude_none=True)
        except ValidationError as exc:
            return JSONResponse(
                {"error": exc.errors()},
                status_code=422,
            )
    else:
        kwargs = body

    # Auth attribution from headers (sanitized, capped at 128 chars)
    user_id = (request.headers.get("X-User-Id") or "anonymous").strip()[:128]
    session_id = (request.headers.get("X-Session-Id") or "unknown").strip()[:128]

    # Rate limit
    if not request.app.state.rate_limiter.allow(name):
        return JSONResponse(
            {"error": "Rate limit exceeded. Try again shortly."},
            status_code=429,
        )

    # Invoke tool
    start = _time.monotonic()
    try:
        result = fn(**kwargs)
        duration = (_time.monotonic() - start) * 1000
        if hasattr(request.app.state, "audit"):
            request.app.state.audit.record(
                tool=name, params=kwargs, status="success",
                duration_ms=duration,
                user_id=user_id, session_id=session_id,
                metadata={"files_read": len(kwargs.get("file_paths") or [])},
            )
        return JSONResponse(result)
    except Exception as exc:
        duration = (_time.monotonic() - start) * 1000
        if hasattr(request.app.state, "audit"):
            request.app.state.audit.record(
                tool=name, params=kwargs, status="error",
                duration_ms=duration, error=str(exc),
                user_id=user_id, session_id=session_id,
            )
        logger.error("Tool %s failed: %s", name, exc, exc_info=True)
        return JSONResponse(
            {"error": f"Tool execution failed: {type(exc).__name__}"},
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

    app.state.rate_limiter = create_rate_limiter()
    app.state.audit = AuditTrail()

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["Content-Type", "X-User-Id", "X-Session-Id"],
    )

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
