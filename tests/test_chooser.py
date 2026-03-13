# tests/test_chooser.py
"""Tests for the integration depth chooser."""
from __future__ import annotations

from typing import Any, Dict, List

import pytest

from three_surgeons.core.chooser import (
    IntegrationDepth,
    IntegrationPlan,
    choose_integration_depth,
)


class TestChooseIntegrationDepth:
    def test_no_capabilities_returns_minimal(self) -> None:
        """No capabilities → only Minimal offered."""
        caps: Dict[str, Any] = {}
        plan = choose_integration_depth(
            capabilities=caps,
            redis_available=True,
            contextdna_available=False,
        )
        assert plan.depth == IntegrationDepth.MINIMAL

    def test_redis_only_returns_minimal(self) -> None:
        """Redis detected, no ContextDNA → Minimal."""
        plan = choose_integration_depth(
            capabilities={},
            redis_available=True,
            contextdna_available=False,
        )
        assert plan.depth == IntegrationDepth.MINIMAL
        assert len(plan.config_changes) > 0

    def test_evidence_store_cap_returns_standard(self) -> None:
        """Redis + evidence_store capability → Standard."""
        caps = {"features": ["evidence_store"], "endpoints": {"evidence": "/api/evidence"}}
        plan = choose_integration_depth(
            capabilities=caps,
            redis_available=True,
            contextdna_available=True,
        )
        assert plan.depth == IntegrationDepth.STANDARD

    def test_all_capabilities_returns_full(self) -> None:
        """Redis + all capabilities → Full."""
        caps = {
            "features": ["evidence_store", "priority_queue", "webhook_injection"],
            "endpoints": {"evidence": "/api/evidence", "priority_queue": "/api/queue"},
        }
        plan = choose_integration_depth(
            capabilities=caps,
            redis_available=True,
            contextdna_available=True,
        )
        assert plan.depth == IntegrationDepth.FULL

    def test_user_preference_overrides(self) -> None:
        """User explicit preference wins."""
        caps = {
            "features": ["evidence_store", "priority_queue"],
            "endpoints": {},
        }
        plan = choose_integration_depth(
            capabilities=caps,
            redis_available=True,
            contextdna_available=True,
            user_preference="minimal",
        )
        assert plan.depth == IntegrationDepth.MINIMAL

    def test_no_redis_no_contextdna(self) -> None:
        """Nothing detected → no plan (stay Phase 1)."""
        plan = choose_integration_depth(
            capabilities={},
            redis_available=False,
            contextdna_available=False,
        )
        assert plan is None

    def test_plan_has_descriptions(self) -> None:
        """Plan includes human-readable descriptions."""
        plan = choose_integration_depth(
            capabilities={},
            redis_available=True,
            contextdna_available=False,
        )
        assert plan is not None
        assert len(plan.description) > 0
        assert len(plan.config_changes) > 0
