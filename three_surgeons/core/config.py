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
        """Read API key from the environment variable.

        Returns None if the env var is missing or the value is < 6 characters.
        """
        value = os.environ.get(self.api_key_env)
        if value is None or len(value) < 6:
            return None
        return value

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


@dataclass
class Config:
    """Top-level configuration for the 3-Surgeons system.

    Atlas (Head Surgeon) is the Claude session itself -- no config needed.
    This configures the two external surgeons plus operational settings.
    """

    cardiologist: SurgeonConfig = field(default_factory=lambda: SurgeonConfig(
        provider="openai",
        endpoint="https://api.openai.com/v1",
        model="gpt-4.1-mini",
        api_key_env="Context_DNA_OPENAI",
        role="External perspective -- cross-examination, evidence",
    ))
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
