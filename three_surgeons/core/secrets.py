"""Secret detection and resolution for 3-Surgeons API keys.

Detects available secret sources on the user's system (env vars, shell profiles,
AWS Secrets Manager, 1Password, macOS Keychain) and either auto-resolves missing
keys or returns a structured RemediationPlan for the coding agent to present
interactive options to the user.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

# All API providers and their standard env var names
PROVIDER_KEY_MAP: Dict[str, str] = {
    "openai": "OPENAI_API_KEY",
    "anthropic": "ANTHROPIC_API_KEY",
    "google": "GOOGLE_API_KEY",
    "deepseek": "DEEPSEEK_API_KEY",
    "groq": "GROQ_API_KEY",
    "xai": "XAI_API_KEY",
    "mistral": "MISTRAL_API_KEY",
    "cohere": "COHERE_API_KEY",
    "perplexity": "PERPLEXITY_API_KEY",
    "together": "TOGETHER_API_KEY",
}

# Providers that run locally and need no API key
LOCAL_PROVIDERS = {"ollama", "mlx", "vllm", "lmstudio"}


@dataclass
class SecretSource:
    """A detected method for resolving a missing API key."""

    method: str          # aws_secretsmanager | 1password | keychain | shell_profile | env | switch_provider
    available: bool
    description: str     # Human-readable explanation
    resolve_command: str  # Shell command the agent should run
    confidence: str      # high | medium | low
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class RemediationPlan:
    """Structured plan for resolving a missing API key."""

    surgeon: str
    provider: str
    key_name: str
    status: str          # resolved | options_available | no_sources | local_no_auth
    resolved: bool
    sources: List[SecretSource] = field(default_factory=list)
    local_alternatives: List[Dict[str, Any]] = field(default_factory=list)
    skip_option: str = "Run with 2/3 surgeons (degraded mode)"

    def to_safe_dict(self) -> Dict[str, Any]:
        """Serialize to dict, excluding any resolved key values."""
        return {
            "surgeon": self.surgeon,
            "provider": self.provider,
            "key_name": self.key_name,
            "status": self.status,
            "resolved": self.resolved,
            "sources": [
                {
                    "method": s.method,
                    "available": s.available,
                    "description": s.description,
                    "resolve_command": s.resolve_command,
                    "confidence": s.confidence,
                    "metadata": s.metadata,
                }
                for s in self.sources
            ],
            "local_alternatives": self.local_alternatives,
            "skip_option": self.skip_option,
        }
