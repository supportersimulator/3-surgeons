"""Shared pytest fixtures for 3-surgeons test suite."""
from __future__ import annotations

import os
import tempfile

import pytest


@pytest.fixture(autouse=True)
def _allow_tmpdir_file_access(monkeypatch: pytest.MonkeyPatch) -> None:
    """Ensure FileAccessPolicy permits files under the system temp dir.

    Tests use pytest's tmp_path which lives outside cwd. This fixture
    adds the real temp directory to THREE_SURGEONS_BASE_DIRS so the
    file access policy accepts test fixture files.
    """
    tmp_root = os.path.realpath(tempfile.gettempdir())
    cwd = os.getcwd()
    monkeypatch.setenv("THREE_SURGEONS_BASE_DIRS", f"{cwd}:{tmp_root}")
