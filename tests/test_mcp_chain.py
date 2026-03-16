"""Tests for chain MCP tool wrappers."""
from __future__ import annotations

from unittest.mock import patch, MagicMock

import pytest

from three_surgeons.mcp.server import (
    _cap_chain_run,
    _cap_chain_presets,
    _cap_chain_suggest,
)


@patch("three_surgeons.mcp.server._build_config")
@patch("three_surgeons.mcp.server.build_runtime_context")
def test_cap_chain_presets(mock_build_ctx, mock_build_config):
    from three_surgeons.core.state import MemoryBackend
    from three_surgeons.core.requirements import RuntimeContext

    mock_build_ctx.return_value = RuntimeContext(
        healthy_llms=[],
        state=MemoryBackend(),
        evidence=None,
        git_available=False,
        git_root=None,
        config=None,
    )

    result = _cap_chain_presets()
    assert "presets" in result
    assert "full-3s" in result["presets"]


@patch("three_surgeons.mcp.server._build_config")
@patch("three_surgeons.mcp.server.build_runtime_context")
def test_cap_chain_suggest_no_trigger(mock_build_ctx, mock_build_config):
    from three_surgeons.core.state import MemoryBackend
    from three_surgeons.core.requirements import RuntimeContext

    mock_build_ctx.return_value = RuntimeContext(
        healthy_llms=[],
        state=MemoryBackend(),
        evidence=None,
        git_available=False,
        git_root=None,
        config=None,
    )

    result = _cap_chain_suggest(trigger="")
    assert result.get("suggestion") is None
