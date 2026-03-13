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


class TestQueueResolution:
    def test_queue_defaults(self, tmp_path: Path) -> None:
        resolver = ConfigResolver(config_dir=tmp_path, probe=False)
        queue = resolver.resolve_queue()
        assert queue.backend == "local"
        assert queue.key_prefix == "3surgeons:gpu_lock"

    def test_queue_from_toml(self, tmp_path: Path) -> None:
        config_file = tmp_path / "config.toml"
        config_file.write_text(
            '[queue]\nbackend = "redis"\nredis_url = "redis://localhost:6379/3"\n'
            'key_prefix = "myapp:gpu_lock"\n'
        )
        resolver = ConfigResolver(config_dir=tmp_path, probe=False)
        queue = resolver.resolve_queue()
        assert queue.backend == "redis"
        assert queue.key_prefix == "myapp:gpu_lock"

    def test_queue_env_override(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("THREE_SURGEONS_QUEUE_BACKEND", "redis")
        resolver = ConfigResolver(config_dir=tmp_path, probe=False)
        queue = resolver.resolve_queue()
        assert queue.backend == "redis"


class TestContextDNAResolution:
    def test_contextdna_defaults_disabled(self, tmp_path: Path) -> None:
        resolver = ConfigResolver(config_dir=tmp_path, probe=False)
        cdna = resolver.resolve_contextdna()
        assert cdna.enabled is False

    def test_contextdna_from_toml(self, tmp_path: Path) -> None:
        config_file = tmp_path / "config.toml"
        config_file.write_text(
            '[contextdna]\nurl = "http://myhost:8029"\nenabled = true\n'
        )
        resolver = ConfigResolver(config_dir=tmp_path, probe=False)
        cdna = resolver.resolve_contextdna()
        assert cdna.enabled is True
        assert cdna.url == "http://myhost:8029"

    def test_contextdna_env_enables(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("THREE_SURGEONS_CONTEXTDNA_URL", "http://remote:8029")
        resolver = ConfigResolver(config_dir=tmp_path, probe=False)
        cdna = resolver.resolve_contextdna()
        assert cdna.enabled is True
        assert cdna.url == "http://remote:8029"


class TestWriteToml:
    def test_write_creates_file(self, tmp_path: Path) -> None:
        resolver = ConfigResolver(config_dir=tmp_path, probe=False)
        resolver.write_toml({"state": {"backend": "redis", "redis_url": "redis://new:6379/0"}})
        assert (tmp_path / "config.toml").is_file()
        resolver2 = ConfigResolver(config_dir=tmp_path, probe=False)
        state = resolver2.resolve_state()
        assert state.backend == "redis"
        assert state.redis_url == "redis://new:6379/0"

    def test_write_preserves_existing_sections(self, tmp_path: Path) -> None:
        config_file = tmp_path / "config.toml"
        config_file.write_text('[state]\nbackend = "sqlite"\n')
        resolver = ConfigResolver(config_dir=tmp_path, probe=False)
        resolver.write_toml({"queue": {"backend": "redis"}})
        resolver2 = ConfigResolver(config_dir=tmp_path, probe=False)
        state = resolver2.resolve_state()
        assert state.backend == "sqlite"
        queue = resolver2.resolve_queue()
        assert queue.backend == "redis"
