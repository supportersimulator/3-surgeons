"""Tests for the config resolution cascade."""
from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import patch

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


class TestConventionProbing:
    def test_redis_probe_succeeds(self, tmp_path: Path) -> None:
        """When probe=True and Redis responds to PING, backend upgrades to redis."""
        with patch("three_surgeons.core.config_resolver.ConfigResolver._probe_redis", return_value=True):
            resolver = ConfigResolver(config_dir=tmp_path, probe=True)
            state = resolver.resolve_state()
            assert state.backend == "redis"

    def test_redis_probe_fails_keeps_sqlite(self, tmp_path: Path) -> None:
        """When probe=True but Redis is down, backend stays sqlite."""
        with patch("three_surgeons.core.config_resolver.ConfigResolver._probe_redis", return_value=False):
            resolver = ConfigResolver(config_dir=tmp_path, probe=True)
            state = resolver.resolve_state()
            assert state.backend == "sqlite"

    def test_contextdna_probe_succeeds(self, tmp_path: Path) -> None:
        """When ContextDNA responds to /health, it's enabled."""
        with patch("three_surgeons.core.config_resolver.ConfigResolver._probe_redis", return_value=False), \
             patch("three_surgeons.core.config_resolver.ConfigResolver._probe_contextdna", return_value=True):
            resolver = ConfigResolver(config_dir=tmp_path, probe=True)
            cdna = resolver.resolve_contextdna()
            assert cdna.enabled is True

    def test_toml_beats_probe(self, tmp_path: Path) -> None:
        """TOML explicit config takes priority over probe results."""
        config_file = tmp_path / "config.toml"
        config_file.write_text('[state]\nbackend = "sqlite"\n')
        with patch("three_surgeons.core.config_resolver.ConfigResolver._probe_redis", return_value=True):
            resolver = ConfigResolver(config_dir=tmp_path, probe=True)
            state = resolver.resolve_state()
            assert state.backend == "sqlite"


class TestCapabilityNegotiation:
    def test_fetch_capabilities_success(self, tmp_path: Path) -> None:
        """Successful GET /capabilities populates capabilities dict."""
        mock_response = {
            "version": "1.0",
            "features": ["evidence_store", "priority_queue"],
            "phase_support": [1, 2],
            "endpoints": {
                "evidence": "/api/evidence",
                "capabilities": "/capabilities",
            },
        }
        with patch("three_surgeons.core.config_resolver.ConfigResolver._fetch_capabilities",
                    return_value=mock_response):
            resolver = ConfigResolver(config_dir=tmp_path, probe=False)
            caps = resolver.negotiate_capabilities("http://localhost:8029")
            assert caps["version"] == "1.0"
            assert "evidence_store" in caps["features"]

    def test_fetch_capabilities_timeout(self, tmp_path: Path) -> None:
        """Timeout returns empty capabilities (graceful degradation)."""
        with patch("three_surgeons.core.config_resolver.ConfigResolver._fetch_capabilities",
                    return_value=None):
            resolver = ConfigResolver(config_dir=tmp_path, probe=False)
            caps = resolver.negotiate_capabilities("http://localhost:8029")
            assert caps is None

    def test_has_capability(self, tmp_path: Path) -> None:
        """Check specific feature from capability response."""
        mock_caps = {
            "version": "1.0",
            "features": ["evidence_store", "webhook_injection"],
            "endpoints": {},
        }
        with patch("three_surgeons.core.config_resolver.ConfigResolver._fetch_capabilities",
                    return_value=mock_caps):
            resolver = ConfigResolver(config_dir=tmp_path, probe=False)
            caps = resolver.negotiate_capabilities("http://localhost:8029")
            assert resolver.has_capability(caps, "evidence_store") is True
            assert resolver.has_capability(caps, "priority_queue") is False
