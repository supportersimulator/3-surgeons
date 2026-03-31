"""Secret detection and resolution for 3-Surgeons API keys.

Detects available secret sources on the user's system (env vars, shell profiles,
AWS Secrets Manager, 1Password, macOS Keychain) and either auto-resolves missing
keys or returns a structured RemediationPlan for the coding agent to present
interactive options to the user.
"""
from __future__ import annotations

import json
import logging
import os
import re
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from three_surgeons.core.config import Config, detect_local_backend

logger = logging.getLogger(__name__)

_SUBPROCESS_TIMEOUT = 10  # seconds

# All API providers and their standard env var names
PROVIDER_KEY_MAP: Dict[str, str] = {
    "openai": "Context_DNA_OPENAI",
    "anthropic": "ANTHROPIC_API_KEY",
    "google": "GOOGLE_API_KEY",
    "deepseek": "Context_DNA_Deepseek",
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


# ---------------------------------------------------------------------------
# Detection probes
# ---------------------------------------------------------------------------


def _probe_env(key_name: str) -> Optional[SecretSource]:
    """Check if the key exists in the current environment."""
    value = os.environ.get(key_name)
    if value and len(value) >= 6:
        return SecretSource(
            method="env",
            available=True,
            description=f"{key_name} found in environment",
            resolve_command="",
            confidence="high",
            metadata={"key_name": key_name},
        )
    return None


def _probe_shell_profile(
    key_name: str,
    search_paths: Optional[List[Path]] = None,
) -> Optional[SecretSource]:
    """Scan shell profiles for an export of the given key."""
    if search_paths is None:
        home = Path.home()
        search_paths = [
            home / ".zshrc",
            home / ".bashrc",
            home / ".bash_profile",
            home / ".zprofile",
            home / ".zshenv",
        ]

    for profile_path in search_paths:
        if not profile_path.is_file():
            continue
        try:
            content = profile_path.read_text()
        except OSError:
            continue
        pattern = rf"^export\s+{re.escape(key_name)}=(.+)$"
        match = re.search(pattern, content, re.MULTILINE)
        if not match:
            continue
        export_line = match.group(0).strip()
        value_part = match.group(1).strip().strip('"').strip("'")

        if "$(" in value_part or "`" in value_part:
            return SecretSource(
                method="shell_profile",
                available=True,
                description=f"Found {key_name} export in {profile_path.name} (uses command substitution)",
                resolve_command=export_line,
                confidence="high",
                metadata={"profile": str(profile_path), "line": export_line, "uses_command": True},
            )
        else:
            return SecretSource(
                method="shell_profile",
                available=True,
                description=f"Found {key_name} export in {profile_path.name}",
                resolve_command=export_line,
                confidence="high",
                metadata={"profile": str(profile_path), "line": export_line, "uses_command": False},
            )
    return None


def _probe_aws(key_name: str, provider: str) -> Optional[SecretSource]:
    """Check for AWS Secrets Manager access and matching secrets."""
    if not shutil.which("aws"):
        return None
    try:
        auth_check = subprocess.run(
            ["aws", "sts", "get-caller-identity"],
            capture_output=True, text=True, timeout=_SUBPROCESS_TIMEOUT,
        )
        if auth_check.returncode != 0:
            return None
    except (subprocess.TimeoutExpired, OSError):
        return None

    try:
        list_result = subprocess.run(
            [
                "aws", "secretsmanager", "list-secrets",
                "--filter", f"Key=name,Values={provider}",
            ],
            capture_output=True, text=True, timeout=_SUBPROCESS_TIMEOUT,
        )
        if list_result.returncode != 0:
            return SecretSource(
                method="aws_secretsmanager",
                available=True,
                description=f"AWS CLI authenticated (no '{provider}' secrets found — specify secret ID manually)",
                resolve_command="aws secretsmanager get-secret-value --secret-id YOUR_SECRET_ID --query SecretString --output text",
                confidence="medium",
                metadata={"aws_authenticated": True, "secrets_found": []},
            )
        data = json.loads(list_result.stdout)
        secrets = data.get("SecretList", [])
        if not secrets:
            return SecretSource(
                method="aws_secretsmanager",
                available=True,
                description=f"AWS CLI authenticated (no '{provider}' secrets found — specify secret ID manually)",
                resolve_command="aws secretsmanager get-secret-value --secret-id YOUR_SECRET_ID --query SecretString --output text",
                confidence="medium",
                metadata={"aws_authenticated": True, "secrets_found": []},
            )
        secret_name = secrets[0]["Name"]
        return SecretSource(
            method="aws_secretsmanager",
            available=True,
            description=f"AWS Secrets Manager — found '{secret_name}'",
            resolve_command=f"aws secretsmanager get-secret-value --secret-id {secret_name} --query SecretString --output text",
            confidence="high",
            metadata={
                "aws_authenticated": True,
                "secret_id": secret_name,
                "secrets_found": [s["Name"] for s in secrets],
            },
        )
    except (subprocess.TimeoutExpired, OSError, json.JSONDecodeError):
        return None


def _probe_1password(key_name: str, provider: str) -> Optional[SecretSource]:
    """Check for 1Password CLI access."""
    if not shutil.which("op"):
        return None
    try:
        account_check = subprocess.run(
            ["op", "account", "list", "--format=json"],
            capture_output=True, text=True, timeout=_SUBPROCESS_TIMEOUT,
        )
        if account_check.returncode != 0:
            return None
        return SecretSource(
            method="1password",
            available=True,
            description="1Password CLI detected and authenticated",
            resolve_command=f'op item get "{provider}" --fields credential --format json',
            confidence="medium",
            metadata={"provider": provider},
        )
    except (subprocess.TimeoutExpired, OSError):
        return None


def _probe_keychain(surgeon_name: str) -> Optional[SecretSource]:
    """Check macOS Keychain for stored key."""
    if not shutil.which("security"):
        return None
    service_name = f"3surgeons-{surgeon_name}"
    try:
        result = subprocess.run(
            ["security", "find-generic-password", "-s", service_name, "-w"],
            capture_output=True, text=True, timeout=_SUBPROCESS_TIMEOUT,
        )
        if result.returncode == 0 and result.stdout.strip():
            return SecretSource(
                method="keychain",
                available=True,
                description=f"Found key in macOS Keychain (service: {service_name})",
                resolve_command=f"security find-generic-password -s {service_name} -w",
                confidence="high",
                metadata={"service": service_name, "exists": True},
            )
        else:
            return SecretSource(
                method="keychain",
                available=True,
                description=f"macOS Keychain available — no existing entry for {service_name}",
                resolve_command=f"security add-generic-password -s {service_name} -a 3surgeons -w YOUR_API_KEY",
                confidence="low",
                metadata={"service": service_name, "exists": False},
            )
    except (subprocess.TimeoutExpired, OSError):
        return None


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------


def diagnose_auth(surgeon_name: str, config: Config) -> RemediationPlan:
    """Detect available secret sources and attempt auto-resolution.

    1. Read surgeon config
    2. If local provider → return immediately (no auth needed)
    3. Check env var (fast path)
    4. Probe secret sources: shell profile, AWS, 1Password, Keychain
    5. Detect local backend alternatives
    6. Return structured plan
    """
    surgeon_cfg = getattr(config, surgeon_name, None)
    if surgeon_cfg is None:
        return RemediationPlan(
            surgeon=surgeon_name,
            provider="unknown",
            key_name="",
            status="no_sources",
            resolved=False,
        )

    provider = surgeon_cfg.provider
    key_name = surgeon_cfg.api_key_env or PROVIDER_KEY_MAP.get(provider, "")

    # Local providers don't need auth
    if provider in LOCAL_PROVIDERS:
        return RemediationPlan(
            surgeon=surgeon_name,
            provider=provider,
            key_name="",
            status="local_no_auth",
            resolved=True,
        )

    sources: List[SecretSource] = []

    # 1. Check env var (fast path)
    env_source = _probe_env(key_name)
    if env_source is not None:
        return RemediationPlan(
            surgeon=surgeon_name,
            provider=provider,
            key_name=key_name,
            status="resolved",
            resolved=True,
            sources=[env_source],
        )

    # 2. Shell profile
    shell_source = _probe_shell_profile(key_name)
    if shell_source is not None:
        # Attempt auto-resolve: if it's a simple value (not command substitution)
        if not shell_source.metadata.get("uses_command"):
            line = shell_source.metadata.get("line", "")
            match = re.search(rf'{re.escape(key_name)}=["\']?([^"\']+)["\']?', line)
            if match:
                resolved_key = match.group(1)
                if len(resolved_key) >= 6:
                    os.environ[key_name] = resolved_key
                    return RemediationPlan(
                        surgeon=surgeon_name,
                        provider=provider,
                        key_name=key_name,
                        status="resolved",
                        resolved=True,
                        sources=[shell_source],
                    )
        sources.append(shell_source)

    # 3. AWS Secrets Manager
    aws_source = _probe_aws(key_name, provider)
    if aws_source is not None:
        sources.append(aws_source)

    # 4. 1Password
    op_source = _probe_1password(key_name, provider)
    if op_source is not None:
        sources.append(op_source)

    # 5. macOS Keychain
    keychain_source = _probe_keychain(surgeon_name)
    if keychain_source is not None:
        sources.append(keychain_source)

    # 6. Detect local alternatives
    local_alts: List[Dict[str, Any]] = []
    try:
        detected = detect_local_backend(timeout_s=2.0)
        local_alts = detected
    except Exception:
        pass

    status = "options_available" if sources else "no_sources"

    return RemediationPlan(
        surgeon=surgeon_name,
        provider=provider,
        key_name=key_name,
        status=status,
        resolved=False,
        sources=sources,
        local_alternatives=local_alts,
    )
