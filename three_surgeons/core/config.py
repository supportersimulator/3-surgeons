"""Configuration system for the 3-Surgeons multi-model consensus plugin.

Loads surgeon, budget, evidence, and gate settings from YAML files
with a discovery order: project .3surgeons.yaml > ~/.3surgeons/config.yaml > defaults.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml

import httpx


# Known local LLM backends: (provider_name, default_port, models_endpoint_path)
LOCAL_BACKENDS = [
    ("ollama", 11434, "/v1/models"),
    ("mlx", 5044, "/v1/models"),
    ("vllm", 8000, "/v1/models"),
    ("lmstudio", 1234, "/v1/models"),
]

# ZSF: keychain-fallback observability counter (merge-resolve 2026-05-08).
_KEYCHAIN_ERRORS: Dict[str, Any] = {"count": 0, "last": ""}

# ZSF: neurologist fallback-chain observability counters (QQ1 2026-05-08).
# Increments whenever resolve_neurologist_with_fallback() picks a provider.
# The "default" key tracks the no-flap case (ollama up, ollama wins) so a
# spike in non-default keys signals a fleet-wide degradation event.
# Surfaced via bridge-status / get_neuro_fallback_counters().
_NEURO_FALLBACK_COUNTERS: Dict[str, int] = {
    "ollama": 0,
    "mlx": 0,
    "mlx_proxy": 0,
    "deepseek": 0,
    "default_kept": 0,  # no fallback ran — env var or CLI flag honored
    "no_provider_reachable": 0,  # all probes failed AND no deepseek key
}

# ZSF: cardiologist fallback-chain observability counters (AAA1 2026-05-12).
# Mirrors the neurologist counters above. RR5/WW5/ZZ5 documented the user
# pain: Anthropic billing inactive → cardio hard-pin → both surgeons end
# up DeepSeek → sycophancy. This counter set surfaces silent failover so
# operators can spot fleet-wide degradation events. Surfaced via
# /health.zsf_counters.three_surgeons.cardio_fallback (file-backed).
_CARDIO_FALLBACK_COUNTERS: Dict[str, int] = {
    "openai": 0,
    "anthropic": 0,
    "deepseek": 0,
    "default_kept": 0,  # no fallback ran — env var/YAML override honored
    "no_provider_reachable": 0,  # entire chain missed (no keys, no probes)
}


def get_neuro_fallback_counters() -> Dict[str, int]:
    """Return a snapshot of the neurologist fallback-chain counters."""
    return dict(_NEURO_FALLBACK_COUNTERS)


def reset_neuro_fallback_counters() -> None:
    """Reset counters — used by tests to isolate runs."""
    for k in _NEURO_FALLBACK_COUNTERS:
        _NEURO_FALLBACK_COUNTERS[k] = 0


def get_cardio_fallback_counters() -> Dict[str, int]:
    """Return a snapshot of the cardiologist fallback-chain counters."""
    return dict(_CARDIO_FALLBACK_COUNTERS)


def reset_cardio_fallback_counters() -> None:
    """Reset counters — used by tests to isolate runs."""
    for k in _CARDIO_FALLBACK_COUNTERS:
        _CARDIO_FALLBACK_COUNTERS[k] = 0


def _persist_counters_zsf() -> None:
    """ZSF best-effort: surface counters to disk for the fleet daemon.

    See ``zsf_counter_persist`` for rationale (RR1 2026-05-08). Lazy
    import keeps this module independent at module-load time. Failures
    inside the persister are absorbed there; this wrapper protects
    against import errors so no caller of a counter bump can crash.
    """
    try:
        from three_surgeons.core.zsf_counter_persist import persist_counters
        persist_counters()
    except Exception:  # noqa: BLE001 — ZSF
        pass


# ── Cardiologist provider presets ─────────────────────────────────────
#
# The Cardiologist is the external (cloud) surgeon in the default 3-Surgeons
# deployment. Historically it has been pinned to OpenAI gpt-4.1-mini. These
# presets let users flip the Cardiologist to an OpenAI-compatible drop-in
# (currently DeepSeek) without editing YAML — either via the ``3s
# --cardio-provider=deepseek`` CLI flag or a ``surgeons.cardiologist.provider``
# value in ``.3surgeons.yaml``.
#
# OpenAI stays the default for backward compatibility. DeepSeek uses the
# OpenAI-compatible ``/v1/chat/completions`` endpoint so no adapter changes
# are needed — only routing (endpoint + model + api_key_env).

CARDIOLOGIST_PROVIDER_PRESETS: Dict[str, Dict[str, str]] = {
    "openai": {
        "provider": "openai",
        "endpoint": "https://api.openai.com/v1",
        "model": "gpt-4.1-mini",
        "api_key_env": "Context_DNA_OPENAI",
    },
    "deepseek": {
        "provider": "deepseek",
        "endpoint": "https://api.deepseek.com/v1",
        # gpt-4.1-mini / gpt-4o-mini → deepseek-chat (general cross-examination);
        # users who want o1-mini-style reasoning can set model=deepseek-reasoner
        # in their YAML.
        "model": "deepseek-chat",
        # Primary env var — DEEPSEEK_API_KEY is also honored as a fallback
        # by SurgeonConfig.get_api_key() for the DeepSeek provider.
        "api_key_env": "Context_DNA_Deepseek",
    },
    # SS2 2026-05-08 — Anthropic preset added to restore the 3-surgeon
    # invariant when both OpenAI billing is inactive (RR5 finding) and
    # neurologist is pinned to DeepSeek (CLAUDE.md 2026-04-26 cutover).
    # Without this preset, both surgeons would collapse to the same
    # provider and the cross-examination signal goes to zero.
    #
    # Uses Anthropic's OpenAI-compatible endpoint (/v1/chat/completions
    # with Authorization: Bearer), so no SDK dependency or new HTTP
    # branch is required — the existing _single_query path handles it.
    # The native Anthropic typed-block content path in _single_query
    # already supports content as a list-of-blocks if Anthropic returns
    # that shape on the compat endpoint.
    #
    # Default model: claude-haiku-4-5-20251001 (cheapest+fastest tier
    # per CLAUDE.md). Users wanting higher quality can override via
    # surgeons.cardiologist.model in .3surgeons.yaml.
    #
    # Env var: Context_DNA_Anthropic primary, ANTHROPIC_API_KEY honored
    # as a fallback by SurgeonConfig.get_api_key() for the anthropic
    # provider (parity with the deepseek fallback chain).
    "anthropic": {
        "provider": "anthropic",
        "endpoint": "https://api.anthropic.com/v1",
        "model": "claude-haiku-4-5-20251001",
        "api_key_env": "Context_DNA_Anthropic",
    },
}


# Map common OpenAI cardiologist models to their DeepSeek equivalents so
# callers can translate a YAML model string when flipping providers.
OPENAI_TO_DEEPSEEK_MODEL: Dict[str, str] = {
    "gpt-4.1-mini": "deepseek-chat",
    "gpt-4o-mini": "deepseek-chat",
    "gpt-4.1-nano": "deepseek-chat",
    "gpt-4.1": "deepseek-chat",
    "o1-mini": "deepseek-reasoner",
    "o3-mini": "deepseek-reasoner",
    "o4-mini": "deepseek-reasoner",
}


# Auto-fallback chain order for the cardiologist (AAA1 2026-05-12).
# Mirrors NEUROLOGIST_FALLBACK_CHAIN (QQ1 2026-05-08).
# Order rationale (LLL1 2026-05-12: flipped to deepseek-first per CLAUDE.md
# 2026-04-26 steady-state directive; OpenAI billing_not_active since RR5):
#   1. deepseek   — steady-state per CLAUDE.md 2026-04-26; cheap + reliable.
#   2. anthropic  — diversity tier (SS2 preset). Used when DeepSeek key absent.
#   3. openai     — legacy fallback for OSS nodes with only an OpenAI key.
# Walked only when no explicit env-var/CLI/YAML override is in effect.
CARDIOLOGIST_FALLBACK_CHAIN: List[str] = ["deepseek", "anthropic", "openai"]


# ── Neurologist provider presets ─────────────────────────────────────
#
# The Neurologist is the "local" surgeon. Default routes to a local
# OpenAI-compatible backend (ollama qwen3:4b). CLAUDE.md 2026-04-26 directive
# noted DeepSeek-chat as the steady-state target for both surgeons; this
# preset table makes the cutover an env-var flip rather than a code edit,
# parity with the cardio path. Default REMAINS ollama for backward
# compatibility — set ``CONTEXT_DNA_NEURO_PROVIDER=deepseek`` (or pass
# ``3s --neuro-provider deepseek``) to flip per-invocation.

NEUROLOGIST_PROVIDER_PRESETS: Dict[str, Dict[str, str]] = {
    "ollama": {
        "provider": "ollama",
        "endpoint": "http://localhost:11434/v1",
        "model": "qwen3:4b",
        "api_key_env": "",
    },
    "mlx": {
        "provider": "mlx",
        "endpoint": "http://localhost:5044/v1",
        "model": "mlx-community/Qwen3-4B-4bit",
        "api_key_env": "",
    },
    # The LLM priority queue proxy (CLAUDE.md: never call MLX directly,
    # route through llm_priority_queue at :5045). Same OpenAI-compatible
    # surface, but routes via the priority queue so 3-surgeons doesn't
    # stampede MLX during high-traffic cardio/neuro turns.
    "mlx_proxy": {
        "provider": "mlx",
        "endpoint": "http://localhost:5045/v1",
        "model": "local-llm",
        "api_key_env": "",
    },
    "deepseek": {
        "provider": "deepseek",
        "endpoint": "https://api.deepseek.com/v1",
        "model": "deepseek-chat",
        "api_key_env": "Context_DNA_Deepseek",
    },
}


# Auto-fallback chain order for the neurologist (QQ1 2026-05-08).
# When neither CONTEXT_DNA_NEURO_PROVIDER env var nor --neuro-provider CLI
# flag is set, Config.discover() walks this list and picks the first
# reachable provider. Probe order = local-fastest first → cloud last.
NEUROLOGIST_FALLBACK_CHAIN: List[str] = ["ollama", "mlx", "mlx_proxy", "deepseek"]


def neurologist_provider_preset(provider: str) -> Dict[str, str]:
    """Return the neurologist preset dict for ``provider``.

    Raises ``ValueError`` on unknown providers so mis-spelled CLI flags or
    env vars surface immediately.
    """
    key = (provider or "").strip().lower()
    if key not in NEUROLOGIST_PROVIDER_PRESETS:
        supported = ", ".join(sorted(NEUROLOGIST_PROVIDER_PRESETS.keys()))
        raise ValueError(
            f"Unknown neurologist provider '{provider}'. Supported: {supported}."
        )
    return dict(NEUROLOGIST_PROVIDER_PRESETS[key])


def make_neurologist_config(
    provider: str = "ollama",
    model: Optional[str] = None,
    endpoint: Optional[str] = None,
    api_key_env: Optional[str] = None,
    role: str = "Local intelligence -- pattern recognition, corrigibility",
) -> "SurgeonConfig":
    """Build a ``SurgeonConfig`` for the neurologist using a provider preset."""
    preset = neurologist_provider_preset(provider)
    return SurgeonConfig(
        provider=preset["provider"],
        endpoint=endpoint or preset["endpoint"],
        model=model or preset["model"],
        api_key_env=api_key_env if api_key_env is not None else preset["api_key_env"],
        role=role,
    )


def cardiologist_provider_preset(provider: str) -> Dict[str, str]:
    """Return the cardiologist preset dict for ``provider``.

    Raises ``ValueError`` for unknown providers so mis-spelled CLI flags
    surface immediately rather than silently falling back to OpenAI.
    """
    key = (provider or "").strip().lower()
    if key not in CARDIOLOGIST_PROVIDER_PRESETS:
        supported = ", ".join(sorted(CARDIOLOGIST_PROVIDER_PRESETS.keys()))
        raise ValueError(
            f"Unknown cardiologist provider '{provider}'. Supported: {supported}."
        )
    return dict(CARDIOLOGIST_PROVIDER_PRESETS[key])


def make_cardiologist_config(
    provider: str = "openai",
    model: Optional[str] = None,
    endpoint: Optional[str] = None,
    api_key_env: Optional[str] = None,
    role: str = "External perspective -- cross-examination, evidence",
) -> "SurgeonConfig":
    """Build a ``SurgeonConfig`` for the cardiologist using a provider preset.

    ``openai`` (default) preserves the legacy behavior. ``deepseek`` routes to
    the DeepSeek OpenAI-compatible endpoint. Any field can be overridden —
    when ``model`` is left ``None`` while flipping from an OpenAI model name,
    ``OPENAI_TO_DEEPSEEK_MODEL`` translates it automatically.
    """
    preset = cardiologist_provider_preset(provider)
    resolved_model = model or preset["model"]
    # Auto-translate OpenAI-style model names when the caller asks for
    # DeepSeek but passed an OpenAI model string.
    if preset["provider"] == "deepseek" and resolved_model in OPENAI_TO_DEEPSEEK_MODEL:
        resolved_model = OPENAI_TO_DEEPSEEK_MODEL[resolved_model]
    return SurgeonConfig(
        provider=preset["provider"],
        endpoint=endpoint or preset["endpoint"],
        model=resolved_model,
        api_key_env=api_key_env or preset["api_key_env"],
        role=role,
    )


class MissingProviderKeyError(RuntimeError):
    """Raised when a cardiologist provider is selected but its API key is absent."""


def _probe_provider_reachable(provider_key: str, timeout_s: float = 2.0) -> bool:
    """Return True if the given neurologist preset is reachable.

    Reachability rules (QQ1 2026-05-08):
      * local providers (ollama, mlx, mlx_proxy): GET ``<endpoint>/models``
        with ``timeout_s``. 200 OK == reachable. Any error / non-2xx == unreachable.
      * deepseek (cloud): require an API key (env or keychain). We do NOT
        ping the cloud endpoint — keys + reachable network is good enough,
        and a probe would burn quota on every CLI invocation.

    ZSF: never raises; returns False on any unexpected error.
    """
    try:
        preset = NEUROLOGIST_PROVIDER_PRESETS.get(provider_key)
        if not preset:
            return False
        if preset["provider"] == "deepseek":
            # Build a temporary SurgeonConfig solely to reuse the standard
            # 3-tier key resolution (env → alt-env → keychain).
            tmp = SurgeonConfig(
                provider=preset["provider"],
                endpoint=preset["endpoint"],
                model=preset["model"],
                api_key_env=preset["api_key_env"],
            )
            return tmp.get_api_key() is not None
        # Local: probe /v1/models
        url = f"{preset['endpoint'].rstrip('/')}/models"
        resp = httpx.get(url, timeout=timeout_s)
        return resp.status_code == 200
    except (httpx.ConnectError, httpx.TimeoutException, httpx.HTTPError, OSError, ValueError):
        return False
    except Exception:  # noqa: BLE001 — ZSF outer guard, never crash discovery
        return False


def _probe_cardio_provider_reachable(provider_key: str, timeout_s: float = 2.0) -> bool:
    """Return True if the given cardiologist preset is reachable.

    AAA1 2026-05-12 — mirrors ``_probe_provider_reachable`` (QQ1) for the
    cardio chain. All three current cardio providers (openai, anthropic,
    deepseek) are cloud services, so the probe is key-only:

      * Key resolvable via the standard 3-tier chain (env → alt-env → keychain)
        → return True.
      * Otherwise → return False.

    Why no HTTP ping?
      Hitting ``/v1/models`` on every CLI invocation would burn quota and
      add cold-call latency (~300ms × 3 providers). Reachability for cloud
      providers is dominated by "is the key valid", not "is the network up";
      the actual call later still surfaces 401/429/network errors via the
      normal surgeon error path. This matches the QQ1 contract for the
      deepseek leg of the neuro chain.

    ZSF: never raises; returns False on any unexpected error.
    """
    try:
        preset = CARDIOLOGIST_PROVIDER_PRESETS.get(provider_key)
        if not preset:
            return False
        tmp = SurgeonConfig(
            provider=preset["provider"],
            endpoint=preset["endpoint"],
            model=preset["model"],
            api_key_env=preset["api_key_env"],
        )
        return tmp.get_api_key() is not None
    except (OSError, ValueError):
        return False
    except Exception:  # noqa: BLE001 — ZSF outer guard, never crash discovery
        return False


def detect_local_backend(timeout_s: float = 2.0) -> list[dict]:
    """Probe common local LLM ports and return detected backends.

    Returns a list of dicts: [{provider, port, endpoint, models}] for each
    backend that responds to /v1/models with valid JSON.
    Does NOT assume what's on a port -- validates via /v1/models response.
    """
    detected = []
    for provider, port, models_path in LOCAL_BACKENDS:
        url = f"http://127.0.0.1:{port}{models_path}"
        try:
            resp = httpx.get(url, timeout=timeout_s)
            if resp.status_code == 200:
                data = resp.json()
                models = []
                # OpenAI-compatible format: {"data": [{"id": "model-name"}, ...]}
                if isinstance(data, dict) and "data" in data:
                    models = [m.get("id", "") for m in data["data"] if isinstance(m, dict)]
                detected.append({
                    "provider": provider,
                    "port": port,
                    "endpoint": f"http://127.0.0.1:{port}/v1",
                    "models": models,
                })
        except (httpx.ConnectError, httpx.TimeoutException, Exception):
            continue
    return detected


@dataclass
class SurgeonConfig:
    """Configuration for a single surgeon (LLM endpoint)."""

    provider: str = "openai"
    endpoint: str = ""
    model: str = ""
    api_key_env: str = ""
    role: str = ""
    fallbacks: List[Dict[str, str]] = field(default_factory=list)

    def get_api_key(self) -> Optional[str]:
        """Read API key from environment, then macOS keychain (L2 finding).

        MERGE-RESOLVE 2026-05-08: combine HEAD's DeepSeek alt-env-var chain
        with feat-branch's macOS keychain fallback (3-tier resolution).

        Resolution order:
          1. Configured ``api_key_env`` env var
          2. For DeepSeek: alt env var names (Context_DNA_Deep_Seek,
             Context_DNA_Deepseek, DEEPSEEK_API_KEY)
          3. macOS keychain — ``security find-generic-password`` with two
             service-name patterns: -s <api_key_env> and
             -s fleet-nerve -a <api_key_env>

        Returns None if all three miss or yield < 6 characters.
        """
        primary = os.environ.get(self.api_key_env) if self.api_key_env else None
        if primary is not None and len(primary) >= 6:
            return primary
        # DeepSeek-specific convenience fallback chain (HEAD-style).
        if self.provider == "deepseek":
            for alt in ("Context_DNA_Deep_Seek", "Context_DNA_Deepseek", "DEEPSEEK_API_KEY"):
                v = os.environ.get(alt)
                if v and len(v) >= 6:
                    return v
        # Anthropic convenience fallback (SS2 2026-05-08) — mirrors the
        # DeepSeek pattern. Lets ANTHROPIC_API_KEY work out-of-the-box
        # for users who already export it (Anthropic SDK convention).
        if self.provider == "anthropic":
            for alt in ("Context_DNA_Anthropic", "ANTHROPIC_API_KEY"):
                v = os.environ.get(alt)
                if v and len(v) >= 6:
                    return v
        # Keychain fallback (feat-style) — for launchd/hooks/xbar processes
        # that lack interactive shell env. Tries 2 service-name patterns:
        #   1. -s <api_key_env>                  (service == env var name)
        #   2. -s fleet-nerve -a <api_key_env>   (RACE/CLAUDE.md convention)
        if self.api_key_env:
            try:
                import subprocess
                attempts = [
                    ["security", "find-generic-password", "-s", self.api_key_env, "-w"],
                    ["security", "find-generic-password",
                     "-s", "fleet-nerve", "-a", self.api_key_env, "-w"],
                ]
                for cmd in attempts:
                    rc = subprocess.run(cmd, capture_output=True, text=True, timeout=2)
                    if rc.returncode == 0:
                        val = (rc.stdout or "").strip()
                        if len(val) >= 6:
                            return val
            except (subprocess.SubprocessError, OSError, FileNotFoundError) as exc:
                # ZSF (post-merge tightening): explicit exception types instead
                # of bare Exception. Sandbox/missing-entry/timeout all map here.
                # Caller already handles None as "no key".
                _KEYCHAIN_ERRORS["count"] = _KEYCHAIN_ERRORS.get("count", 0) + 1
                _KEYCHAIN_ERRORS["last"] = str(exc)
                _persist_counters_zsf()
        return None

    def get_fallback_configs(self) -> List["SurgeonConfig"]:
        """Convert fallback dicts from YAML into SurgeonConfig objects."""
        configs = []
        for fb in self.fallbacks:
            if isinstance(fb, dict):
                configs.append(SurgeonConfig(
                    provider=fb.get("provider", "openai"),
                    endpoint=fb.get("endpoint", ""),
                    model=fb.get("model", ""),
                    api_key_env=fb.get("api_key_env", ""),
                ))
        return configs


@dataclass
class BudgetConfig:
    """Spending limits for external LLM calls."""

    daily_external_usd: float = 5.0
    autonomous_ab_usd: float = 2.0


@dataclass
class EvidenceConfig:
    """Evidence store configuration."""

    db_path: str = "~/.3surgeons/evidence.db"

    @property
    def resolved_path(self) -> Path:
        """Return the db_path with ~ expanded to the actual home directory."""
        return Path(self.db_path).expanduser()


@dataclass
class GatesConfig:
    """Gains-gate configuration: checks that must pass before proceeding."""

    gains_gate_checks: List[str] = field(
        default_factory=lambda: [
            "neurologist_health",
            "cardiologist_health",
            "evidence_store",
        ]
    )


@dataclass
class StateConfig:
    """State backend configuration."""

    backend: str = "sqlite"  # sqlite | redis | memory
    sqlite_path: str = "~/.3surgeons/state.db"
    redis_url: str = "redis://localhost:6379/0"

    @property
    def resolved_sqlite_path(self) -> Path:
        """Return sqlite_path with ~ expanded."""
        return Path(self.sqlite_path).expanduser()


@dataclass
class ReviewConfig:
    """Review loop mode configuration."""

    depth: str = "single"       # single | iterative | continuous
    auto_depth: str = "off"     # off | suggest | auto


@dataclass
class QueueConfig:
    """Priority queue configuration. Same interface, expanding backend."""

    backend: str = "local"  # local | redis | distributed
    priorities: List[str] = field(
        default_factory=lambda: ["USER_FACING", "OPERATIONAL", "EXTERNAL", "BACKGROUND"]
    )


@dataclass
class UpgradeConfig:
    """Upgrade adaptability configuration. Full Phase 3 schema from Day 1."""

    polling_interval: int = 300       # Adaptive: 5min start, backs off to 1hr
    last_probe: Optional[str] = None  # ISO timestamp of last probe
    config_hash: Optional[str] = None # SHA256 of config.yaml
    sequence: int = 0                 # Monotonic counter for conflict resolution
    nudge: bool = True                # User can silence with: 3s config set upgrade.nudge false
    # Transaction fields
    transaction_status: Optional[str] = None    # null | "in_progress" | "committed"
    transaction_snapshot: Optional[str] = None  # JSON of full config before upgrade
    revert_target: Optional[int] = None         # Phase to revert to
    quorum_votes: Optional[str] = None          # JSON of surgeon votes


@dataclass
class ChainConfig:
    """Chain orchestration configuration."""
    default_mode: str = "lightweight"
    auto_suggest: bool = True


@dataclass
class ConsultationConfig:
    """Surgeon consultation configuration."""
    cadence: int = 20
    community_sync: bool = True
    community_repo: str = "origin"
    community_branch: str = "community-chains"
    auto_accept_threshold: float = 0.90
    budget_per_consultation_usd: float = 0.02


@dataclass
class TelemetryConfig:
    """Chain telemetry configuration."""
    enabled: bool = True
    retention_days: int = 90
    min_observations_for_pattern: int = 5
    min_frequency_for_pattern: float = 0.75
    min_observations_for_dependency: int = 20
    min_correlation_for_dependency: float = 0.80


def _default_cardiologist() -> "SurgeonConfig":
    """Default cardiologist config, env-aware.

    LLM_PROVIDER=deepseek → route cardiologist to DeepSeek (OpenAI-compatible).
    Otherwise (default/unset) → OpenAI gpt-4.1-mini (legacy behavior preserved).
    """
    provider = os.environ.get("LLM_PROVIDER", "anthropic")
    if provider == "deepseek":
        return SurgeonConfig(
            provider="deepseek",
            endpoint="https://api.deepseek.com/v1",
            model="deepseek-chat",
            api_key_env="Context_DNA_Deep_Seek",
            role="External perspective -- cross-examination, evidence",
        )
    return SurgeonConfig(
        provider="openai",
        endpoint="https://api.openai.com/v1",
        model="gpt-4.1-mini",
        api_key_env="Context_DNA_OPENAI",
        role="External perspective -- cross-examination, evidence",
    )


@dataclass
class Config:
    """Top-level configuration for the 3-Surgeons system.

    Atlas (Head Surgeon) is the Claude session itself -- no config needed.
    This configures the two external surgeons plus operational settings.
    """

    cardiologist: SurgeonConfig = field(default_factory=lambda: _default_cardiologist())
    neurologist: SurgeonConfig = field(default_factory=lambda: SurgeonConfig(
        provider="ollama",
        endpoint="http://localhost:11434/v1",
        model="qwen3:4b",
        api_key_env="",
        role="Local intelligence -- pattern recognition, corrigibility",
    ))
    budgets: BudgetConfig = field(default_factory=BudgetConfig)
    evidence: EvidenceConfig = field(default_factory=EvidenceConfig)
    gates: GatesConfig = field(default_factory=GatesConfig)
    state: StateConfig = field(default_factory=StateConfig)
    gpu_lock_path: Optional[str] = None
    review: ReviewConfig = field(default_factory=ReviewConfig)
    schema_version: int = 1
    phase: int = 1  # Auto-detected, auto-promoted
    queue: QueueConfig = field(default_factory=QueueConfig)
    upgrade: UpgradeConfig = field(default_factory=UpgradeConfig)
    read_only: bool = False
    chains: ChainConfig = field(default_factory=ChainConfig)
    consultation: ConsultationConfig = field(default_factory=ConsultationConfig)
    telemetry: TelemetryConfig = field(default_factory=TelemetryConfig)

    @classmethod
    def from_yaml(cls, path: Path) -> Config:
        """Load configuration from a YAML file.

        Returns default Config if the file does not exist or cannot be parsed.
        """
        if not path.is_file():
            return cls()
        try:
            raw = yaml.safe_load(path.read_text()) or {}
        except (yaml.YAMLError, OSError):
            return cls()
        return cls._from_dict(raw)

    @classmethod
    def discover(cls, project_dir: Optional[Path] = None) -> Config:
        """Discover and merge configuration across tiers.

        Layers (each overrides the previous):
        1. Built-in defaults (base)
        2. ~/.3surgeons/config.yaml (user-level overrides)
        3. project_dir/.3surgeons.yaml (project-level overrides)

        Project config inherits from user config, which inherits from
        defaults. Only the fields explicitly set in a tier override the
        tier below -- unset fields are preserved from the lower tier.
        """
        # Start with defaults
        cfg = cls()

        # Layer user-level config
        home_config = Path.home() / ".3surgeons" / "config.yaml"
        if home_config.is_file():
            try:
                raw = yaml.safe_load(home_config.read_text()) or {}
            except (yaml.YAMLError, OSError):
                raw = {}
            cfg = cls._merge_into(cfg, raw)

        # Layer project-level config on top
        if project_dir is not None:
            project_config = project_dir / ".3surgeons.yaml"
            if project_config.is_file():
                try:
                    raw = yaml.safe_load(project_config.read_text()) or {}
                except (yaml.YAMLError, OSError):
                    raw = {}
                cfg = cls._merge_into(cfg, raw)

        # Env-var overrides — final layer, highest precedence after CLI flags.
        # CONTEXT_DNA_NEURO_PROVIDER allows fleet-wide cutover without YAML
        # edits per CLAUDE.md 2026-04-26 directive. require_key=False here so
        # `3s probe` / `3s --help` work without keys; commands that actually
        # call the model surface the key error via the normal path.
        neuro_env = os.environ.get("CONTEXT_DNA_NEURO_PROVIDER")
        if neuro_env:
            try:
                cfg.apply_neurologist_provider(neuro_env, require_key=False)
            except ValueError:
                # Bogus env var — preserve default rather than crash discovery.
                pass
            # Explicit override → counter bump; no fallback run.
            _NEURO_FALLBACK_COUNTERS["default_kept"] = (
                _NEURO_FALLBACK_COUNTERS.get("default_kept", 0) + 1
            )
            _persist_counters_zsf()
        else:
            # QQ1 2026-05-08 — no explicit override → walk the fallback chain
            # so degraded nodes silently upgrade to the next reachable provider
            # (ollama → mlx → mlx_proxy → deepseek). On healthy nodes ollama
            # wins on the first probe, preserving today's default behavior.
            # Disabled by setting CONTEXT_DNA_NEURO_FALLBACK_DISABLE=1 — useful
            # for tests / air-gapped scenarios that want strict legacy
            # "default = ollama no matter what" behavior.
            if os.environ.get("CONTEXT_DNA_NEURO_FALLBACK_DISABLE") != "1":
                try:
                    cfg.resolve_neurologist_with_fallback()
                except Exception:  # noqa: BLE001 — ZSF: discover() must never crash
                    pass

        # AAA1 2026-05-12 — mirror the neuro chain for the cardiologist.
        # CONTEXT_DNA_CARDIO_PROVIDER explicit override wins (parity with
        # the neuro env var). When absent, walk CARDIOLOGIST_FALLBACK_CHAIN
        # to silently upgrade degraded nodes. Kill-switch:
        # CONTEXT_DNA_CARDIO_FALLBACK_DISABLE=1 for tests / strict legacy.
        cardio_env = os.environ.get("CONTEXT_DNA_CARDIO_PROVIDER")
        if cardio_env:
            try:
                cfg.apply_cardiologist_provider(cardio_env, require_key=False)
            except ValueError:
                # Bogus env var — preserve default rather than crash discovery.
                pass
            # Explicit override → counter bump; no fallback run.
            _CARDIO_FALLBACK_COUNTERS["default_kept"] = (
                _CARDIO_FALLBACK_COUNTERS.get("default_kept", 0) + 1
            )
            _persist_counters_zsf()
        else:
            if os.environ.get("CONTEXT_DNA_CARDIO_FALLBACK_DISABLE") != "1":
                try:
                    cfg.resolve_cardiologist_with_fallback()
                except Exception:  # noqa: BLE001 — ZSF: discover() must never crash
                    pass

        return cfg

    @classmethod
    def _from_dict(cls, raw: Dict[str, Any]) -> Config:
        """Parse a raw dict (from YAML) into a Config from defaults.

        Only sets fields that exist in the corresponding dataclass,
        ignoring unknown keys gracefully.
        """
        return cls._merge_into(cls(), raw)

    @classmethod
    def _merge_into(cls, cfg: Config, raw: Dict[str, Any]) -> Config:
        """Merge a raw dict into an existing Config, overriding only set fields.

        This enables layered config: defaults → user → project, where each
        layer only overrides what it explicitly sets.
        """
        if not isinstance(raw, dict):
            return cfg

        surgeons = raw.get("surgeons", {})
        if isinstance(surgeons, dict):
            if "cardiologist" in surgeons:
                cfg.cardiologist = _merge_surgeon(cfg.cardiologist, surgeons["cardiologist"])
            if "neurologist" in surgeons:
                cfg.neurologist = _merge_surgeon(cfg.neurologist, surgeons["neurologist"])

        budgets_raw = raw.get("budgets", {})
        if isinstance(budgets_raw, dict):
            cfg.budgets = _merge_dataclass(cfg.budgets, budgets_raw)

        evidence_raw = raw.get("evidence", {})
        if isinstance(evidence_raw, dict):
            cfg.evidence = _merge_dataclass(cfg.evidence, evidence_raw)

        gates_raw = raw.get("gates", {})
        if isinstance(gates_raw, dict):
            cfg.gates = _merge_dataclass(cfg.gates, gates_raw)

        state_raw = raw.get("state", {})
        if isinstance(state_raw, dict):
            cfg.state = _merge_dataclass(cfg.state, state_raw)

        review_raw = raw.get("review", {})
        if isinstance(review_raw, dict):
            cfg.review = _merge_dataclass(cfg.review, review_raw)

        # Top-level scalars
        if "schema_version" in raw:
            cfg.schema_version = raw["schema_version"]
        if "phase" in raw:
            cfg.phase = raw["phase"]

        queue_raw = raw.get("queue", {})
        if isinstance(queue_raw, dict):
            cfg.queue = _merge_dataclass(cfg.queue, queue_raw)

        upgrade_raw = raw.get("upgrade", {})
        if isinstance(upgrade_raw, dict):
            cfg.upgrade = _merge_dataclass(cfg.upgrade, upgrade_raw)

        chains_raw = raw.get("chains", {})
        if isinstance(chains_raw, dict):
            cfg.chains = _merge_dataclass(cfg.chains, chains_raw)

        consultation_raw = raw.get("consultation", {})
        if isinstance(consultation_raw, dict):
            cfg.consultation = _merge_dataclass(cfg.consultation, consultation_raw)

        telemetry_raw = raw.get("telemetry", {})
        if isinstance(telemetry_raw, dict):
            cfg.telemetry = _merge_dataclass(cfg.telemetry, telemetry_raw)

        return cfg

    def resolve_neurologist_with_fallback(
        self,
        chain: Optional[List[str]] = None,
        probe_timeout_s: float = 2.0,
    ) -> "Config":
        """Walk the neurologist fallback chain and apply the first reachable provider.

        QQ1 2026-05-08 — fixes the silent single-surgeon degradation reported by
        PP1 (commit 83b21e29b): on hosts where ollama is down (e.g. mac3) the
        default ``3s consensus`` returned ``Neurologist: unavailable`` rather
        than failing over to mlx / proxy / DeepSeek.

        Caller contract:
          * Only call this when neither ``CONTEXT_DNA_NEURO_PROVIDER`` nor
            ``--neuro-provider`` was supplied. Explicit overrides MUST win.
          * Mutates ``self.neurologist`` to the first reachable preset.
          * If nothing in the chain is reachable, leaves ``self.neurologist``
            untouched (current default — fail-safe behavior so that the rest
            of the pipeline still emits a friendly "neurologist unavailable"
            warning rather than a config crash).

        Increments ZSF observability counters on every choice:
        ``_NEURO_FALLBACK_COUNTERS[<chosen>]`` and, when ollama wins (the
        default), also ``default_kept`` so dashboards distinguish "ollama up"
        from "active failover landed on ollama after probing it."
        """
        ladder = chain if chain is not None else NEUROLOGIST_FALLBACK_CHAIN
        for provider_key in ladder:
            if _probe_provider_reachable(provider_key, timeout_s=probe_timeout_s):
                # Apply preset. require_key=False because reachability already
                # verified the key for deepseek; for local providers it's a
                # no-op anyway.
                try:
                    self.apply_neurologist_provider(provider_key, require_key=False)
                except ValueError:
                    # Bogus chain entry — skip and keep walking.
                    continue
                _NEURO_FALLBACK_COUNTERS[provider_key] = (
                    _NEURO_FALLBACK_COUNTERS.get(provider_key, 0) + 1
                )
                _persist_counters_zsf()
                return self
        # Nothing reachable. Record the miss so dashboards see degraded fleet.
        _NEURO_FALLBACK_COUNTERS["no_provider_reachable"] = (
            _NEURO_FALLBACK_COUNTERS.get("no_provider_reachable", 0) + 1
        )
        _persist_counters_zsf()
        return self

    def resolve_cardiologist_with_fallback(
        self,
        chain: Optional[List[str]] = None,
        probe_timeout_s: float = 2.0,
    ) -> "Config":
        """Walk the cardiologist fallback chain and apply the first reachable provider.

        AAA1 2026-05-12 — mirrors ``resolve_neurologist_with_fallback`` (QQ1).
        Fixes the silent single-cloud-surgeon degradation reported by RR5 / WW5
        / ZZ5: when Anthropic billing is inactive AND cardiologist is hard-pinned
        to anthropic, ``3s consensus`` produces zero-diversity output (both
        surgeons fall back to deepseek → sycophancy). With this method wired
        into ``Config.discover()`` the cardiologist now silently upgrades to
        the next reachable provider in the chain.

        Caller contract (parity with QQ1):
          * Only call this when no explicit cardiologist provider override has
            been supplied (``CONTEXT_DNA_CARDIO_PROVIDER`` env var or
            ``--cardio-provider`` CLI flag). Explicit overrides MUST win.
          * Mutates ``self.cardiologist`` to the first reachable preset.
          * If nothing in the chain is reachable (e.g. no keys configured at
            all), leaves ``self.cardiologist`` untouched so the rest of the
            pipeline still emits a friendly "cardiologist unavailable" warning
            rather than a config crash.

        Increments ZSF observability counters on every choice. Surfaced via
        ``/health.zsf_counters.three_surgeons.cardio_fallback``.
        """
        ladder = chain if chain is not None else CARDIOLOGIST_FALLBACK_CHAIN
        for provider_key in ladder:
            if _probe_cardio_provider_reachable(provider_key, timeout_s=probe_timeout_s):
                try:
                    # require_key=False — probe already confirmed key resolves;
                    # a redundant resolve here would just repeat the keychain
                    # subprocess for no benefit.
                    self.apply_cardiologist_provider(provider_key, require_key=False)
                except ValueError:
                    # Bogus chain entry (unknown provider name) — skip and
                    # keep walking the chain.
                    continue
                except MissingProviderKeyError:
                    # Race: key disappeared between probe and apply. Skip.
                    continue
                _CARDIO_FALLBACK_COUNTERS[provider_key] = (
                    _CARDIO_FALLBACK_COUNTERS.get(provider_key, 0) + 1
                )
                _persist_counters_zsf()
                return self
        # Nothing reachable. Record the miss so dashboards see degraded fleet.
        _CARDIO_FALLBACK_COUNTERS["no_provider_reachable"] = (
            _CARDIO_FALLBACK_COUNTERS.get("no_provider_reachable", 0) + 1
        )
        _persist_counters_zsf()
        return self

    def apply_cardiologist_provider(
        self,
        provider: str,
        require_key: bool = True,
    ) -> "Config":
        """Swap the cardiologist to a provider preset (openai | deepseek).

        Mutates this Config in place and returns ``self`` for chaining.
        Preserves the cardiologist's ``role`` and ``fallbacks``. When
        ``require_key`` is True (the default), raises ``MissingProviderKeyError``
        if the resulting provider cannot resolve an API key from the
        environment — this gives CLI users an immediate, actionable error.
        """
        preset_cfg = make_cardiologist_config(
            provider=provider,
            # If the user YAML specifies an OpenAI model and we're flipping
            # to DeepSeek, auto-translate — otherwise keep their override.
            model=None,
            role=self.cardiologist.role or "External perspective -- cross-examination, evidence",
        )
        preset_cfg.fallbacks = list(self.cardiologist.fallbacks or [])
        self.cardiologist = preset_cfg

        if require_key and preset_cfg.get_api_key() is None:
            hint = preset_cfg.api_key_env
            if preset_cfg.provider == "deepseek":
                hint = f"{preset_cfg.api_key_env} (or DEEPSEEK_API_KEY)"
            elif preset_cfg.provider == "anthropic":
                hint = f"{preset_cfg.api_key_env} (or ANTHROPIC_API_KEY)"
            raise MissingProviderKeyError(
                f"Cardiologist provider '{preset_cfg.provider}' selected but no API "
                f"key found. Set {hint} in the environment, macOS Keychain, or "
                f"AWS Secrets Manager (e.g. /ersim/prod/backend/DEEPSEEK_API_KEY)."
            )
        return self

    def apply_neurologist_provider(
        self,
        provider: str,
        require_key: bool = True,
    ) -> "Config":
        """Swap the neurologist to a provider preset (ollama | mlx | deepseek).

        Mutates this Config in place and returns ``self`` for chaining.
        Preserves the neurologist's ``role`` and ``fallbacks``. When
        ``require_key`` is True (default) and the chosen provider needs a key
        (e.g. deepseek), raises ``MissingProviderKeyError`` if not resolvable.

        Local providers (ollama/mlx) skip the key check.
        """
        preset_cfg = make_neurologist_config(
            provider=provider,
            model=None,
            role=self.neurologist.role
            or "Local intelligence -- pattern recognition, corrigibility",
        )
        preset_cfg.fallbacks = list(self.neurologist.fallbacks or [])
        self.neurologist = preset_cfg

        if (
            require_key
            and preset_cfg.api_key_env
            and preset_cfg.get_api_key() is None
        ):
            hint = preset_cfg.api_key_env
            if preset_cfg.provider == "deepseek":
                hint = f"{preset_cfg.api_key_env} (or DEEPSEEK_API_KEY)"
            raise MissingProviderKeyError(
                f"Neurologist provider '{preset_cfg.provider}' selected but no API "
                f"key found. Set {hint} in the environment, macOS Keychain, or "
                f"AWS Secrets Manager."
            )
        return self


def _merge_surgeon(default: SurgeonConfig, overrides: Dict[str, Any]) -> SurgeonConfig:
    """Merge overrides into a SurgeonConfig, only setting known fields."""
    return _merge_dataclass(default, overrides)


def _merge_dataclass(default: Any, overrides: Dict[str, Any]) -> Any:
    """Merge a dict of overrides into a dataclass instance.

    Only sets attributes that already exist on the dataclass.
    Returns a new instance with merged values.
    """
    if not isinstance(overrides, dict):
        return default
    # Get the known field names from the dataclass
    known_fields = {f.name for f in default.__dataclass_fields__.values()}
    merged = {}
    for fname in known_fields:
        if fname in overrides:
            merged[fname] = overrides[fname]
        else:
            merged[fname] = getattr(default, fname)
    return type(default)(**merged)
