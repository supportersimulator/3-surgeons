"""Tests for the 3-Surgeons configuration system."""
from __future__ import annotations

import os
from pathlib import Path

import pytest
import yaml

from three_surgeons.core.config import Config, SurgeonConfig


class TestLoadFromYaml:
    """Test loading configuration from a YAML file."""

    def test_load_from_yaml(self, tmp_path: Path) -> None:
        """Write a config YAML to tmp_path, load it, verify surgeon fields."""
        config_data = {
            "surgeons": {
                "cardiologist": {
                    "provider": "openai",
                    "endpoint": "https://api.openai.com/v1",
                    "model": "gpt-4.1-mini",
                    "api_key_env": "Context_DNA_OPENAI",
                    "role": "External perspective",
                },
                "neurologist": {
                    "provider": "ollama",
                    "endpoint": "http://localhost:11434/v1",
                    "model": "qwen3:4b",
                    "role": "Local intelligence",
                },
            },
            "budgets": {
                "daily_external_usd": 10.0,
                "autonomous_ab_usd": 3.0,
            },
            "evidence": {
                "db_path": "~/.3surgeons/evidence.db",
            },
        }
        yaml_path = tmp_path / "config.yaml"
        yaml_path.write_text(yaml.dump(config_data))

        cfg = Config.from_yaml(yaml_path)

        assert cfg.cardiologist.provider == "openai"
        assert cfg.cardiologist.endpoint == "https://api.openai.com/v1"
        assert cfg.cardiologist.model == "gpt-4.1-mini"
        assert cfg.cardiologist.api_key_env == "Context_DNA_OPENAI"
        assert cfg.cardiologist.role == "External perspective"

        assert cfg.neurologist.provider == "ollama"
        assert cfg.neurologist.endpoint == "http://localhost:11434/v1"
        assert cfg.neurologist.model == "qwen3:4b"
        assert cfg.neurologist.role == "Local intelligence"

        assert cfg.budgets.daily_external_usd == 10.0
        assert cfg.budgets.autonomous_ab_usd == 3.0


class TestLoadDefaults:
    """Test default configuration when no file exists."""

    def test_load_default_when_no_file(self, tmp_path: Path) -> None:
        """Load from nonexistent path, verify defaults are returned."""
        nonexistent = tmp_path / "does_not_exist.yaml"
        cfg = Config.from_yaml(nonexistent)

        # Defaults from the spec
        assert cfg.cardiologist.provider == "openai"
        assert cfg.cardiologist.model == "gpt-4.1-mini"
        assert cfg.cardiologist.api_key_env == "Context_DNA_OPENAI"

        assert cfg.neurologist.provider == "ollama"
        assert cfg.neurologist.model == "qwen3:4b"
        assert cfg.neurologist.endpoint == "http://localhost:11434/v1"

        assert cfg.budgets.daily_external_usd == 5.0
        assert cfg.budgets.autonomous_ab_usd == 2.0

        assert cfg.evidence.db_path == "~/.3surgeons/evidence.db"


class TestApiKey:
    """Test API key retrieval from environment variables."""

    def test_api_key_from_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Set env var, verify get_api_key() returns it."""
        monkeypatch.setenv("TEST_API_KEY_XYZ", "sk-test-key-long-enough")
        surgeon = SurgeonConfig(
            provider="openai",
            endpoint="https://api.openai.com/v1",
            model="gpt-4.1-mini",
            api_key_env="TEST_API_KEY_XYZ",
            role="test",
        )
        assert surgeon.get_api_key() == "sk-test-key-long-enough"

    def test_api_key_missing_returns_none(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """No env var set, verify get_api_key() returns None."""
        monkeypatch.delenv("NONEXISTENT_KEY_VAR", raising=False)
        surgeon = SurgeonConfig(
            provider="openai",
            endpoint="https://api.openai.com/v1",
            model="gpt-4.1-mini",
            api_key_env="NONEXISTENT_KEY_VAR",
            role="test",
        )
        assert surgeon.get_api_key() is None

    def test_api_key_too_short_returns_none(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Env var exists but value is <6 chars, verify get_api_key() returns None."""
        monkeypatch.setenv("SHORT_KEY_VAR", "abc")
        surgeon = SurgeonConfig(
            provider="openai",
            endpoint="https://api.openai.com/v1",
            model="gpt-4.1-mini",
            api_key_env="SHORT_KEY_VAR",
            role="test",
        )
        assert surgeon.get_api_key() is None


class TestConfigDiscovery:
    """Test configuration discovery order."""

    def test_config_discovery_order(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Create both home and project configs, verify project takes priority."""
        # Set up fake home dir with config
        fake_home = tmp_path / "home"
        fake_home.mkdir()
        home_config_dir = fake_home / ".3surgeons"
        home_config_dir.mkdir()
        home_config = home_config_dir / "config.yaml"
        home_config.write_text(yaml.dump({
            "surgeons": {
                "cardiologist": {
                    "model": "gpt-4o-from-home",
                },
            },
        }))

        # Set up project dir with config (should take priority)
        project_dir = tmp_path / "project"
        project_dir.mkdir()
        project_config = project_dir / ".3surgeons.yaml"
        project_config.write_text(yaml.dump({
            "surgeons": {
                "cardiologist": {
                    "model": "gpt-4o-from-project",
                },
            },
        }))

        # Patch HOME so discover() finds our fake home
        monkeypatch.setenv("HOME", str(fake_home))

        cfg = Config.discover(project_dir=project_dir)

        # Project config should win over home config
        assert cfg.cardiologist.model == "gpt-4o-from-project"

    def test_config_discovery_falls_to_home(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """No project config, verify home config is used."""
        fake_home = tmp_path / "home"
        fake_home.mkdir()
        home_config_dir = fake_home / ".3surgeons"
        home_config_dir.mkdir()
        home_config = home_config_dir / "config.yaml"
        home_config.write_text(yaml.dump({
            "surgeons": {
                "cardiologist": {
                    "model": "gpt-4o-from-home",
                },
            },
        }))

        # Project dir exists but has no .3surgeons.yaml
        project_dir = tmp_path / "project"
        project_dir.mkdir()

        monkeypatch.setenv("HOME", str(fake_home))

        cfg = Config.discover(project_dir=project_dir)

        assert cfg.cardiologist.model == "gpt-4o-from-home"

    def test_config_discovery_falls_to_defaults(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """No config files anywhere, verify defaults are returned.

        QQ1 2026-05-08: ``CONTEXT_DNA_NEURO_FALLBACK_DISABLE=1`` is set so the
        neurologist auto-fallback chain doesn't probe live local services
        on the test host (which would silently flip the model to mlx).
        """
        fake_home = tmp_path / "empty_home"
        fake_home.mkdir()

        project_dir = tmp_path / "empty_project"
        project_dir.mkdir()

        monkeypatch.setenv("HOME", str(fake_home))
        monkeypatch.setenv("CONTEXT_DNA_NEURO_FALLBACK_DISABLE", "1")

        cfg = Config.discover(project_dir=project_dir)

        # Should be defaults
        assert cfg.cardiologist.model == "gpt-4.1-mini"
        assert cfg.neurologist.model == "qwen3:4b"


class TestEvidencePath:
    """Test evidence config path resolution."""

    def test_resolved_path_expands_user(self) -> None:
        """Verify resolved_path expands ~ to actual home directory."""
        from three_surgeons.core.config import EvidenceConfig

        evidence = EvidenceConfig(db_path="~/.3surgeons/evidence.db")
        resolved = evidence.resolved_path
        assert isinstance(resolved, Path)
        assert "~" not in str(resolved)
        assert str(resolved).endswith(".3surgeons/evidence.db")


class TestGatesConfig:
    """Test gates configuration defaults."""

    def test_default_gates(self) -> None:
        """Verify default gates checks list."""
        from three_surgeons.core.config import GatesConfig

        gates = GatesConfig()
        assert "neurologist_health" in gates.gains_gate_checks
        assert "cardiologist_health" in gates.gains_gate_checks
        assert "evidence_store" in gates.gains_gate_checks


def test_state_config_defaults():
    """StateConfig should default to sqlite backend."""
    from three_surgeons.core.config import StateConfig
    sc = StateConfig()
    assert sc.backend == "sqlite"
    assert sc.sqlite_path == "~/.3surgeons/state.db"
    assert sc.redis_url == "redis://localhost:6379/0"


def test_state_config_resolved_sqlite_path():
    from three_surgeons.core.config import StateConfig
    sc = StateConfig()
    resolved = sc.resolved_sqlite_path
    assert "~" not in str(resolved)
    assert str(resolved).endswith("state.db")


def test_config_has_state():
    from three_surgeons.core.config import Config
    cfg = Config()
    assert cfg.state.backend == "sqlite"


def test_config_from_yaml_with_state(tmp_path):
    from three_surgeons.core.config import Config
    yaml_file = tmp_path / "test.yaml"
    yaml_file.write_text("state:\n  backend: redis\n  redis_url: redis://myhost:6380/1\n")
    cfg = Config.from_yaml(yaml_file)
    assert cfg.state.backend == "redis"
    assert cfg.state.redis_url == "redis://myhost:6380/1"


def test_preset_api_only_loads():
    from three_surgeons.core.config import Config
    preset = Path(__file__).parent.parent / "config" / "presets" / "api-only.yaml"
    assert preset.exists(), "api-only.yaml preset missing"
    cfg = Config.from_yaml(preset)
    assert cfg.cardiologist.provider == "openai"
    assert cfg.neurologist.api_key_env == "Context_DNA_Deepseek"


def test_preset_local_only_loads():
    from three_surgeons.core.config import Config
    preset = Path(__file__).parent.parent / "config" / "presets" / "local-only.yaml"
    assert preset.exists(), "local-only.yaml preset missing"
    cfg = Config.from_yaml(preset)
    assert cfg.cardiologist.provider == "local"
    assert cfg.neurologist.provider == "local"


def test_preset_hybrid_loads():
    from three_surgeons.core.config import Config
    preset = Path(__file__).parent.parent / "config" / "presets" / "hybrid.yaml"
    assert preset.exists(), "hybrid.yaml preset missing"
    cfg = Config.from_yaml(preset)
    assert cfg.cardiologist.provider == "openai"
    assert cfg.neurologist.provider == "ollama"


class TestReviewConfig:
    """Review depth configuration fields."""

    def test_default_review_depth_is_single(self):
        from three_surgeons.core.config import Config
        config = Config()
        assert config.review.depth == "single"

    def test_default_auto_review_depth_is_off(self):
        from three_surgeons.core.config import Config
        config = Config()
        assert config.review.auto_depth == "off"

    def test_review_config_from_yaml(self, tmp_path):
        from three_surgeons.core.config import Config
        yaml_content = (
            "review:\n"
            "  depth: continuous\n"
            "  auto_depth: suggest\n"
        )
        yaml_path = tmp_path / "config.yaml"
        yaml_path.write_text(yaml_content)
        config = Config.from_yaml(yaml_path)
        assert config.review.depth == "continuous"
        assert config.review.auto_depth == "suggest"

    def test_auto_depth_validates_values(self):
        from three_surgeons.core.config import Config
        config = Config()
        config.review.auto_depth = "auto"
        assert config.review.auto_depth in ("off", "suggest", "auto")


from three_surgeons.core.config import UpgradeConfig, QueueConfig


class TestUpgradeConfig:
    def test_defaults(self) -> None:
        uc = UpgradeConfig()
        assert uc.polling_interval == 300
        assert uc.last_probe is None
        assert uc.config_hash is None
        assert uc.sequence == 0
        assert uc.nudge is True
        assert uc.transaction_status is None
        assert uc.transaction_snapshot is None
        assert uc.revert_target is None
        assert uc.quorum_votes is None

    def test_phase_default_is_1(self) -> None:
        cfg = Config()
        assert cfg.phase == 1
        assert cfg.schema_version == 1


class TestQueueConfig:
    def test_defaults(self) -> None:
        qc = QueueConfig()
        assert qc.backend == "local"
        assert qc.priorities == ["USER_FACING", "OPERATIONAL", "EXTERNAL", "BACKGROUND"]


class TestConfigWithUpgrade:
    def test_config_has_upgrade(self) -> None:
        cfg = Config()
        assert isinstance(cfg.upgrade, UpgradeConfig)

    def test_config_has_queue(self) -> None:
        cfg = Config()
        assert isinstance(cfg.queue, QueueConfig)

    def test_yaml_roundtrip_upgrade(self, tmp_path) -> None:
        import yaml
        config_file = tmp_path / "config.yaml"
        config_file.write_text(yaml.dump({
            "phase": 2,
            "upgrade": {
                "polling_interval": 600,
                "nudge": False,
            },
            "queue": {
                "backend": "redis",
            },
        }))
        cfg = Config.from_yaml(config_file)
        assert cfg.phase == 2
        assert cfg.upgrade.polling_interval == 600
        assert cfg.upgrade.nudge is False
        assert cfg.queue.backend == "redis"
