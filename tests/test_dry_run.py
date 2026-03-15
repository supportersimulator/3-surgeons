"""Test dry-run mode and DryRunResult."""
import pytest
from three_surgeons.core.config import Config
from three_surgeons.core.dry_run import DryRunResult, check_dry_run


def test_config_has_read_only():
    cfg = Config()
    assert hasattr(cfg, "read_only")
    assert cfg.read_only is False


def test_dry_run_result():
    result = DryRunResult(
        tool="cross_examine",
        would_call=["cardiologist", "neurologist"],
        estimated_cost_usd=0.003,
        plan="Phase 1: Query both surgeons independently. Phase 2: Cross-examine. Phase 3: Synthesize.",
    )
    assert result.tool == "cross_examine"
    assert len(result.would_call) == 2
    d = result.to_dict()
    assert d["dry_run"] is True
    assert "estimated_cost_usd" in d


def test_check_dry_run_returns_result():
    result = check_dry_run("probe", {})
    assert result is not None
    assert result.dry_run is True
    assert result.tool == "probe"


def test_check_dry_run_with_args():
    result = check_dry_run("cross_examine", {"topic": "test"})
    assert result.tool == "cross_examine"
    assert "test" in result.plan
