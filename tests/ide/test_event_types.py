"""Tests for event schema validation and namespace registry."""
from __future__ import annotations

import pytest

from three_surgeons.ide.event_types import (
    NAMESPACE_REGISTRY,
    EventNamespace,
    InvalidEventTypeError,
    parse_event_type,
    validate_event_type,
)


class TestNamespaceRegistry:

    def test_all_namespaces_registered(self):
        expected = {
            "injection", "evidence", "skill", "health",
            "ide", "surgeon", "phase", "breaker",
        }
        assert {ns.value for ns in EventNamespace} == expected

    def test_registry_has_examples(self):
        for ns in EventNamespace:
            assert ns in NAMESPACE_REGISTRY
            info = NAMESPACE_REGISTRY[ns]
            assert "examples" in info
            assert len(info["examples"]) > 0


class TestValidateEventType:

    def test_valid_event_type(self):
        assert validate_event_type("injection.completed") is True

    def test_valid_custom_suffix(self):
        assert validate_event_type("health.degraded") is True

    def test_invalid_no_dot(self):
        with pytest.raises(InvalidEventTypeError):
            validate_event_type("injection")

    def test_invalid_namespace(self):
        with pytest.raises(InvalidEventTypeError):
            validate_event_type("unknown.event")

    def test_breaker_namespace_valid(self):
        assert validate_event_type("breaker.tripped") is True


class TestParseEventType:

    def test_parse_simple(self):
        ns, action = parse_event_type("injection.completed")
        assert ns == EventNamespace.INJECTION
        assert action == "completed"

    def test_parse_compound_action(self):
        ns, action = parse_event_type("surgeon.cross_exam_started")
        assert ns == EventNamespace.SURGEON
        assert action == "cross_exam_started"


class TestEventDirection:

    def test_python_to_ts_namespaces(self):
        py_to_ts = {"injection", "evidence", "health", "surgeon", "phase"}
        for ns_name in py_to_ts:
            ns = EventNamespace(ns_name)
            assert NAMESPACE_REGISTRY[ns]["direction"] in (
                "python_to_ts", "bidirectional"
            )

    def test_ts_to_python_namespaces(self):
        ns = EventNamespace.IDE
        assert NAMESPACE_REGISTRY[ns]["direction"] in (
            "ts_to_python", "bidirectional"
        )

    def test_bidirectional_namespaces(self):
        ns = EventNamespace.SKILL
        assert NAMESPACE_REGISTRY[ns]["direction"] == "bidirectional"
