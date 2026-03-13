"""Tests for the config resolution cascade."""
from __future__ import annotations

import os
from pathlib import Path

import pytest

from three_surgeons.core.config_resolver import ConfigResolver


class TestConfigResolver:
    def test_defaults_when_no_config(self, tmp_path: Path) -> None:
        """No env vars, no config file, no probing → defaults."""
        resolver = ConfigResolver(config_dir=tmp_path, probe=False)
        state = resolver.resolve_state()
        assert state.backend == "sqlite"
        assert "state.db" in state.sqlite_path

    def test_env_override_redis_url(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """ENV var takes precedence over everything."""
        monkeypatch.setenv("THREE_SURGEONS_REDIS_URL", "redis://custom:6380/1")
        resolver = ConfigResolver(config_dir=tmp_path, probe=False)
        state = resolver.resolve_state()
        assert state.backend == "redis"
        assert state.redis_url == "redis://custom:6380/1"

    def test_toml_config_read(self, tmp_path: Path) -> None:
        """TOML config file populates state config."""
        config_file = tmp_path / "config.toml"
        config_file.write_text(
            '[state]\nbackend = "redis"\nredis_url = "redis://localhost:6379/2"\n'
        )
        resolver = ConfigResolver(config_dir=tmp_path, probe=False)
        state = resolver.resolve_state()
        assert state.backend == "redis"
        assert state.redis_url == "redis://localhost:6379/2"

    def test_env_beats_toml(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """ENV override wins over TOML file."""
        config_file = tmp_path / "config.toml"
        config_file.write_text(
            '[state]\nbackend = "redis"\nredis_url = "redis://from-toml:6379/0"\n'
        )
        monkeypatch.setenv("THREE_SURGEONS_REDIS_URL", "redis://from-env:6380/1")
        resolver = ConfigResolver(config_dir=tmp_path, probe=False)
        state = resolver.resolve_state()
        assert state.redis_url == "redis://from-env:6380/1"
