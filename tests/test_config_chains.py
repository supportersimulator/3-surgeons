"""Tests for chain-related config sections."""
from __future__ import annotations

import pytest

from three_surgeons.core.config import (
    ChainConfig,
    ConsultationConfig,
    TelemetryConfig,
    Config,
)


def test_chain_config_defaults():
    cc = ChainConfig()
    assert cc.default_mode == "lightweight"
    assert cc.auto_suggest is True


def test_consultation_config_defaults():
    cc = ConsultationConfig()
    assert cc.cadence == 20
    assert cc.community_sync is True


def test_telemetry_config_defaults():
    tc = TelemetryConfig()
    assert tc.enabled is True
    assert tc.retention_days == 90


def test_config_has_chain_fields():
    cfg = Config()
    assert hasattr(cfg, "chains")
    assert hasattr(cfg, "consultation")
    assert hasattr(cfg, "telemetry")
    assert isinstance(cfg.chains, ChainConfig)


def test_config_merge_chain_section():
    cfg = Config()
    raw = {"chains": {"default_mode": "full-3s", "auto_suggest": False}}
    merged = Config._merge_into(cfg, raw)
    assert merged.chains.default_mode == "full-3s"
    assert merged.chains.auto_suggest is False
