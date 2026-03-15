"""Tests for capability-adaptive HTTP endpoints."""
from __future__ import annotations

import pytest

from three_surgeons.http.schemas import TOOL_SCHEMAS


class TestHttpSchemas:
    """Verify all 11 new schemas are registered."""

    EXPECTED = [
        "cap_status", "cap_research_status",
        "cap_ab_veto", "cap_ab_queue", "cap_ab_start",
        "cap_ab_measure", "cap_ab_conclude", "cap_ab_collaborate",
        "cap_research_evidence", "cap_cardio_reverify", "cap_deep_audit",
    ]

    def test_schemas_registered(self):
        for name in self.EXPECTED:
            assert name in TOOL_SCHEMAS, f"Schema '{name}' not in TOOL_SCHEMAS"

    def test_schema_validation(self):
        """Verify schemas validate correctly."""
        schema = TOOL_SCHEMAS["cap_ab_veto"]
        validated = schema.model_validate({"test_id": "t1", "reason": "bad"})
        assert validated.test_id == "t1"
        assert validated.reason == "bad"

    def test_schema_rejects_empty(self):
        """Verify required fields are enforced."""
        from pydantic import ValidationError
        schema = TOOL_SCHEMAS["cap_ab_veto"]
        with pytest.raises(ValidationError):
            schema.model_validate({})


class TestHttpToolRegistry:
    """Verify all 11 new tools are in BASE_TOOLS."""

    def test_base_tools_registered(self):
        from three_surgeons.http.server import BASE_TOOLS
        expected = [
            "cap_status", "cap_research_status",
            "cap_ab_veto", "cap_ab_queue", "cap_ab_start",
            "cap_ab_measure", "cap_ab_conclude", "cap_ab_collaborate",
            "cap_research_evidence", "cap_cardio_reverify", "cap_deep_audit",
        ]
        for name in expected:
            assert name in BASE_TOOLS, f"Tool '{name}' not in BASE_TOOLS"

    def test_fn_names_point_to_cap_functions(self):
        from three_surgeons.http.server import BASE_TOOLS
        for name, spec in BASE_TOOLS.items():
            if name.startswith("cap_"):
                assert spec["fn_name"].startswith("_cap_"), \
                    f"Tool '{name}' fn_name should start with '_cap_'"
