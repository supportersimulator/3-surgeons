"""Tests for python -m three_surgeons.http entry point."""
from __future__ import annotations

import runpy
import sys
from unittest.mock import patch, MagicMock


class TestHttpMain:
    """Verify __main__.py wires up correctly."""

    @patch("uvicorn.run")
    @patch("three_surgeons.http.server.create_app")
    def test_main_calls_uvicorn_with_defaults(self, mock_create_app, mock_run):
        mock_app = MagicMock()
        mock_create_app.return_value = mock_app

        # Remove from cache so re-import executes module code
        mod_name = "three_surgeons.http.__main__"
        if mod_name in sys.modules:
            del sys.modules[mod_name]

        # run_module sets __name__ = "__main__", triggering the guard
        runpy.run_module("three_surgeons.http", run_name="__main__")

        mock_create_app.assert_called_once()
        mock_run.assert_called_once_with(mock_app, host="127.0.0.1", port=3456)
