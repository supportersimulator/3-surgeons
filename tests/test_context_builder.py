"""Tests for RuntimeContext builder."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from three_surgeons.core.requirements import RuntimeContext


def _mock_config():
    """Config with cardiologist + neurologist."""
    config = MagicMock()
    config.cardiologist.provider = "openai"
    config.cardiologist.endpoint = "https://api.openai.com/v1"
    config.cardiologist.get_api_key.return_value = "sk-test"
    config.neurologist.provider = "ollama"
    config.neurologist.endpoint = "http://localhost:11434/v1"
    config.neurologist.get_api_key.return_value = None
    config.evidence.resolved_path = "/tmp/test-evidence.db"
    config.state.backend = "memory"
    config.gpu_lock_path = None
    return config


class TestBuildRuntimeContext:
    def test_import(self):
        from three_surgeons.core.context_builder import build_runtime_context
        assert callable(build_runtime_context)

    @patch("three_surgeons.core.context_builder._probe_llm_health")
    @patch("three_surgeons.core.context_builder._detect_git")
    @patch("three_surgeons.core.context_builder.create_backend_from_config")
    @patch("three_surgeons.core.context_builder.EvidenceStore")
    def test_returns_runtime_context(self, mock_ev, mock_backend, mock_git, mock_llm):
        from three_surgeons.core.context_builder import build_runtime_context
        mock_llm.return_value = [MagicMock(), MagicMock()]
        mock_git.return_value = (True, "/repo")
        mock_backend.return_value = MagicMock()
        mock_ev.return_value = MagicMock()

        ctx = build_runtime_context(_mock_config())
        assert isinstance(ctx, RuntimeContext)
        assert len(ctx.healthy_llms) == 2
        assert ctx.git_available is True
        assert ctx.git_root == "/repo"
        assert ctx.state is not None
        assert ctx.evidence is not None

    @patch("three_surgeons.core.context_builder._probe_llm_health")
    @patch("three_surgeons.core.context_builder._detect_git")
    @patch("three_surgeons.core.context_builder.create_backend_from_config")
    @patch("three_surgeons.core.context_builder.EvidenceStore")
    def test_no_git(self, mock_ev, mock_backend, mock_git, mock_llm):
        from three_surgeons.core.context_builder import build_runtime_context
        mock_llm.return_value = []
        mock_git.return_value = (False, None)
        mock_backend.return_value = MagicMock()
        mock_ev.return_value = MagicMock()

        ctx = build_runtime_context(_mock_config())
        assert ctx.git_available is False
        assert ctx.git_root is None

    def test_detect_git_in_repo(self, tmp_path):
        from three_surgeons.core.context_builder import _detect_git
        (tmp_path / ".git").mkdir()
        ok, root = _detect_git(str(tmp_path))
        assert isinstance(ok, bool)

    def test_detect_git_not_in_repo(self, tmp_path):
        from three_surgeons.core.context_builder import _detect_git
        ok, root = _detect_git(str(tmp_path))
        assert ok is False
        assert root is None
