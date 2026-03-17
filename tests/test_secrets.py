"""Tests for the secret detection and resolution module."""
from __future__ import annotations

import pytest

from three_surgeons.core.secrets import (
    LOCAL_PROVIDERS,
    PROVIDER_KEY_MAP,
    RemediationPlan,
    SecretSource,
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
            key_name="OPENAI_API_KEY",
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
            key_name="OPENAI_API_KEY",
            status="resolved",
            resolved=True,
            sources=[],
            local_alternatives=[],
            skip_option="Run with 2/3 surgeons (degraded mode)",
        )
        d = plan.to_safe_dict()
        assert "resolved_value" not in str(d)
        assert d["status"] == "resolved"
