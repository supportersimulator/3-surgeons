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


@dataclass
class SurgeonConfig:
    """Configuration for a single surgeon (LLM endpoint)."""

    provider: str = "openai"
    endpoint: str = ""
    model: str = ""
    api_key_env: str = ""
    role: str = ""

    def get_api_key(self) -> Optional[str]:
        """Read API key from the environment variable.

        Returns None if the env var is missing or the value is < 6 characters.
        """
        value = os.environ.get(self.api_key_env)
        if value is None or len(value) < 6:
            return None
        return value


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
class Config:
    """Top-level configuration for the 3-Surgeons system.

    Atlas (Head Surgeon) is the Claude session itself -- no config needed.
    This configures the two external surgeons plus operational settings.
    """

    cardiologist: SurgeonConfig = field(default_factory=lambda: SurgeonConfig(
        provider="openai",
        endpoint="https://api.openai.com/v1",
        model="gpt-4.1-mini",
        api_key_env="OPENAI_API_KEY",
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
        """Discover configuration using a priority order.

        Search order (first found wins):
        1. project_dir/.3surgeons.yaml  (project-level)
        2. ~/.3surgeons/config.yaml     (user-level)
        3. built-in defaults
        """
        # 1. Project-level config
        if project_dir is not None:
            project_config = project_dir / ".3surgeons.yaml"
            if project_config.is_file():
                return cls.from_yaml(project_config)

        # 2. User-level config in home directory
        home_config = Path.home() / ".3surgeons" / "config.yaml"
        if home_config.is_file():
            return cls.from_yaml(home_config)

        # 3. Defaults
        return cls()

    @classmethod
    def _from_dict(cls, raw: Dict[str, Any]) -> Config:
        """Parse a raw dict (from YAML) into a Config.

        Only sets fields that exist in the corresponding dataclass,
        ignoring unknown keys gracefully.
        """
        cfg = cls()

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
