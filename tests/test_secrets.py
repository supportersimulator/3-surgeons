"""Tests for the secret detection and resolution module."""
from __future__ import annotations

import os
from unittest.mock import MagicMock, patch

import pytest

from three_surgeons.core.config import Config, SurgeonConfig
from three_surgeons.core.secrets import (
    LOCAL_PROVIDERS,
    PROVIDER_KEY_MAP,
    RemediationPlan,
    SecretSource,
    _probe_1password,
    _probe_aws,
    _probe_env,
    _probe_keychain,
    _probe_shell_profile,
    diagnose_auth,
)


class TestDataStructures:
    """Verify data structures and provider map."""

    def test_provider_key_map_has_all_api_providers(self) -> None:
        expected = {
            "openai", "anthropic", "google", "deepseek", "groq",
            "xai", "mistral", "cohere", "perplexity", "together",
        }
        assert set(PROVIDER_KEY_MAP.keys()) == expected

    def test_local_providers_skip_auth(self) -> None:
        assert "ollama" in LOCAL_PROVIDERS
        assert "mlx" in LOCAL_PROVIDERS
        assert "vllm" in LOCAL_PROVIDERS
        assert "lmstudio" in LOCAL_PROVIDERS

    def test_secret_source_fields(self) -> None:
        src = SecretSource(
            method="aws_secretsmanager",
            available=True,
            description="AWS CLI detected",
            resolve_command="aws secretsmanager get-secret-value ...",
            confidence="high",
            metadata={"secret_id": "my-key"},
        )
        assert src.method == "aws_secretsmanager"
        assert src.available is True
        assert src.confidence == "high"

    def test_remediation_plan_fields(self) -> None:
        plan = RemediationPlan(
            surgeon="cardiologist",
            provider="openai",
            key_name="Context_DNA_OPENAI",
            status="options_available",
            resolved=False,
            sources=[],
            local_alternatives=[],
            skip_option="Run with 2/3 surgeons (degraded mode)",
        )
        assert plan.surgeon == "cardiologist"
        assert plan.resolved is False

    def test_remediation_plan_to_dict_excludes_resolved_value(self) -> None:
        plan = RemediationPlan(
            surgeon="cardiologist",
            provider="openai",
            key_name="Context_DNA_OPENAI",
            status="resolved",
            resolved=True,
            sources=[],
            local_alternatives=[],
            skip_option="Run with 2/3 surgeons (degraded mode)",
        )
        d = plan.to_safe_dict()
        assert "resolved_value" not in str(d)
        assert d["status"] == "resolved"


class TestProbeEnv:
    """Test environment variable probe."""

    def test_finds_existing_key(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("Context_DNA_OPENAI", "sk-test-1234567890")
        result = _probe_env("Context_DNA_OPENAI")
        assert result is not None
        assert result.method == "env"
        assert result.available is True
        assert result.confidence == "high"

    def test_returns_none_when_missing(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("Context_DNA_OPENAI", raising=False)
        result = _probe_env("Context_DNA_OPENAI")
        assert result is None

    def test_returns_none_for_short_value(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("Context_DNA_OPENAI", "sk")
        result = _probe_env("Context_DNA_OPENAI")
        assert result is None


class TestProbeShellProfile:
    """Test shell profile scanning."""

    def test_finds_export_in_profile(self, tmp_path) -> None:
        zshrc = tmp_path / ".zshrc"
        zshrc.write_text('export Context_DNA_OPENAI="sk-test-1234567890"\n')
        result = _probe_shell_profile("Context_DNA_OPENAI", search_paths=[zshrc])
        assert result is not None
        assert result.method == "shell_profile"
        assert result.available is True
        assert str(zshrc) in result.metadata.get("profile", "")

    def test_finds_aws_secretsmanager_pattern(self, tmp_path) -> None:
        zshrc = tmp_path / ".zshrc"
        zshrc.write_text(
            'export Context_DNA_OPENAI="$(aws secretsmanager get-secret-value '
            '--secret-id MY_KEY --query SecretString --output text)"\n'
        )
        result = _probe_shell_profile("Context_DNA_OPENAI", search_paths=[zshrc])
        assert result is not None
        assert "aws" in result.resolve_command.lower()

    def test_returns_none_when_not_found(self, tmp_path) -> None:
        zshrc = tmp_path / ".zshrc"
        zshrc.write_text("# nothing here\n")
        result = _probe_shell_profile("Context_DNA_OPENAI", search_paths=[zshrc])
        assert result is None


class TestProbeAws:
    """Test AWS Secrets Manager probe."""

    @patch("shutil.which", return_value="/usr/local/bin/aws")
    @patch("subprocess.run")
    def test_detects_aws_cli_and_finds_secret(self, mock_run: MagicMock, _mock_which: MagicMock) -> None:
        identity_result = MagicMock(returncode=0, stdout='{"Account": "123456"}')
        list_result = MagicMock(
            returncode=0,
            stdout='{"SecretList": [{"Name": "my-openai-key", "ARN": "arn:aws:..."}]}',
        )
        mock_run.side_effect = [identity_result, list_result]
        result = _probe_aws("Context_DNA_OPENAI", "openai")
        assert result is not None
        assert result.method == "aws_secretsmanager"
        assert result.available is True
        assert "my-openai-key" in result.resolve_command

    @patch("shutil.which", return_value=None)
    def test_returns_none_without_aws_cli(self, _mock_which: MagicMock) -> None:
        result = _probe_aws("Context_DNA_OPENAI", "openai")
        assert result is None


class TestProbe1Password:
    """Test 1Password CLI probe."""

    @patch("shutil.which", return_value="/usr/local/bin/op")
    @patch("subprocess.run")
    def test_detects_op_cli(self, mock_run: MagicMock, _mock_which: MagicMock) -> None:
        mock_run.return_value = MagicMock(returncode=0, stdout='[{"shorthand": "my"}]')
        result = _probe_1password("Context_DNA_OPENAI", "openai")
        assert result is not None
        assert result.method == "1password"

    @patch("shutil.which", return_value=None)
    def test_returns_none_without_op_cli(self, _mock_which: MagicMock) -> None:
        result = _probe_1password("Context_DNA_OPENAI", "openai")
        assert result is None


class TestProbeKeychain:
    """Test macOS Keychain probe."""

    @patch("shutil.which", return_value="/usr/bin/security")
    @patch("subprocess.run")
    def test_finds_existing_keychain_entry(self, mock_run: MagicMock, _mock_which: MagicMock) -> None:
        mock_run.return_value = MagicMock(returncode=0, stdout="sk-test-key")
        result = _probe_keychain("cardiologist")
        assert result is not None
        assert result.method == "keychain"
        assert result.confidence == "high"

    @patch("shutil.which", return_value="/usr/bin/security")
    @patch("subprocess.run")
    def test_offers_keychain_store_when_no_entry(self, mock_run: MagicMock, _mock_which: MagicMock) -> None:
        mock_run.return_value = MagicMock(returncode=44, stdout="", stderr="not found")
        result = _probe_keychain("cardiologist")
        assert result is not None
        assert result.confidence == "low"
        assert "store" in result.description.lower() or "no existing" in result.description.lower()

    @patch("shutil.which", return_value=None)
    def test_returns_none_on_non_macos(self, _mock_which: MagicMock) -> None:
        result = _probe_keychain("cardiologist")
        assert result is None


class TestDiagnoseAuth:
    """Test the main diagnose_auth entry point."""

    def test_local_provider_skips_auth(self) -> None:
        config = Config()
        config.neurologist = SurgeonConfig(provider="ollama", endpoint="http://localhost:11434/v1")
        plan = diagnose_auth("neurologist", config)
        assert plan.status == "local_no_auth"
        assert plan.resolved is True

    def test_env_var_present_auto_resolves(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("Context_DNA_OPENAI", "sk-test-1234567890")
        config = Config()
        plan = diagnose_auth("cardiologist", config)
        assert plan.status == "resolved"
        assert plan.resolved is True

    def test_env_var_missing_returns_options(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("Context_DNA_OPENAI", raising=False)
        config = Config()
        plan = diagnose_auth("cardiologist", config)
        assert plan.status in ("options_available", "no_sources")
        assert plan.resolved is False
        assert plan.key_name == "Context_DNA_OPENAI"
        assert plan.provider == "openai"

    def test_includes_local_alternatives(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("Context_DNA_OPENAI", raising=False)
        config = Config()
        with patch("three_surgeons.core.secrets.detect_local_backend", return_value=[
            {"provider": "ollama", "port": 11434, "endpoint": "http://127.0.0.1:11434/v1", "models": ["qwen3:4b"]}
        ]):
            plan = diagnose_auth("cardiologist", config)
        assert len(plan.local_alternatives) > 0
        assert plan.local_alternatives[0]["provider"] == "ollama"

    def test_to_safe_dict_is_serializable(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("Context_DNA_OPENAI", raising=False)
        config = Config()
        plan = diagnose_auth("cardiologist", config)
        d = plan.to_safe_dict()
        import json
        json.dumps(d)


class TestProbeIntegration:
    """Test that diagnose_auth returns remediation for auth failures."""

    def test_remediation_on_missing_key(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """When env var is missing, diagnose_auth returns options."""
        monkeypatch.delenv("Context_DNA_OPENAI", raising=False)
        config = Config()
        plan = diagnose_auth("cardiologist", config)
        assert plan.resolved is False
        assert plan.key_name == "Context_DNA_OPENAI"
        d = plan.to_safe_dict()
        assert d["key_name"] == "Context_DNA_OPENAI"
        assert d["status"] in ("options_available", "no_sources")
