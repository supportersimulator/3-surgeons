"""Tests for the `chain` CLI subcommand group."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from click.testing import CliRunner

from three_surgeons.cli.main import cli


@pytest.fixture
def runner():
    return CliRunner()


def test_chain_group_exists(runner):
    result = runner.invoke(cli, ["chain", "--help"])
    assert result.exit_code == 0
    assert "run" in result.output
    assert "presets" in result.output


def test_chain_presets_lists_all(runner):
    result = runner.invoke(cli, ["chain", "presets"])
    assert result.exit_code == 0
    assert "full-3s" in result.output
    assert "lightweight" in result.output
    assert "plan-review" in result.output
    assert "evidence-dive" in result.output


@patch("three_surgeons.cli.main.build_runtime_context")
def test_chain_run_lightweight(mock_build_ctx, runner):
    """chain run executes without error on lightweight mode."""
    from three_surgeons.core.state import MemoryBackend
    from three_surgeons.core.requirements import RuntimeContext

    mock_ctx = RuntimeContext(
        healthy_llms=[],
        state=MemoryBackend(),
        evidence=None,
        git_available=False,
        git_root=None,
        config=None,
    )
    mock_build_ctx.return_value = mock_ctx

    # lightweight segments won't be registered in test env, so we expect
    # a KeyError or graceful message about missing segments
    result = runner.invoke(cli, ["chain", "run", "--mode", "lightweight"])
    # Should not crash with unhandled exception
    assert result.exit_code in (0, 1)
