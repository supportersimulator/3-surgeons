"""Tests for Pydantic request schemas."""
import pytest
from pydantic import ValidationError


class TestCrossExamineRequest:
    def test_valid_minimal(self):
        from three_surgeons.http.schemas import CrossExamineRequest
        req = CrossExamineRequest(topic="test security")
        assert req.topic == "test security"
        assert req.depth == "full"
        assert req.mode == "single"
        assert req.file_paths is None

    def test_valid_with_file_paths(self):
        from three_surgeons.http.schemas import CrossExamineRequest
        req = CrossExamineRequest(
            topic="review", file_paths=["/tmp/a.py", "/tmp/b.py"]
        )
        assert len(req.file_paths) == 2

    def test_missing_topic_raises(self):
        from three_surgeons.http.schemas import CrossExamineRequest
        with pytest.raises(ValidationError, match="topic"):
            CrossExamineRequest()

    def test_invalid_depth_raises(self):
        from three_surgeons.http.schemas import CrossExamineRequest
        with pytest.raises(ValidationError):
            CrossExamineRequest(topic="x", depth="invalid_depth")

    def test_invalid_mode_raises(self):
        from three_surgeons.http.schemas import CrossExamineRequest
        with pytest.raises(ValidationError):
            CrossExamineRequest(topic="x", mode="bad_mode")

    def test_file_paths_must_be_strings(self):
        from three_surgeons.http.schemas import CrossExamineRequest
        with pytest.raises(ValidationError):
            CrossExamineRequest(topic="x", file_paths=[123, 456])


class TestConsultRequest:
    def test_valid(self):
        from three_surgeons.http.schemas import ConsultRequest
        req = ConsultRequest(topic="question")
        assert req.topic == "question"

    def test_missing_topic_raises(self):
        from three_surgeons.http.schemas import ConsultRequest
        with pytest.raises(ValidationError):
            ConsultRequest()


class TestConsensusRequest:
    def test_valid(self):
        from three_surgeons.http.schemas import ConsensusRequest
        req = ConsensusRequest(claim="X is true")
        assert req.claim == "X is true"


class TestSchemaRegistry:
    def test_all_tools_have_schemas(self):
        from three_surgeons.http.schemas import TOOL_SCHEMAS
        assert "cross_examine" in TOOL_SCHEMAS
        assert "consult" in TOOL_SCHEMAS
        assert "consensus" in TOOL_SCHEMAS
        assert "probe" in TOOL_SCHEMAS


# --- New schema coverage tests (Task 1: IDE Versatility) ---

EXPECTED_TOOLS = [
    "probe", "cross_examine", "consult", "consensus",
    "sentinel_run", "gains_gate",
    "ab_propose", "ab_start", "ab_measure", "ab_conclude", "ab_validate_tool",
    "ask_local_tool", "ask_remote_tool",
    "neurologist_pulse_tool", "neurologist_challenge_tool", "introspect_tool",
    "cardio_review_tool", "research_tool",
    "upgrade_probe", "upgrade_history",
    "event_subscribe", "event_unsubscribe", "event_publish", "event_poll",
]


def test_all_tools_have_schemas():
    from three_surgeons.http.schemas import TOOL_SCHEMAS
    for tool in EXPECTED_TOOLS:
        assert tool in TOOL_SCHEMAS, f"Missing schema for tool: {tool}"


def test_sentinel_run_schema():
    from three_surgeons.http.schemas import TOOL_SCHEMAS
    schema = TOOL_SCHEMAS["sentinel_run"]
    validated = schema.model_validate({"content": "test content"})
    assert validated.content == "test content"


def test_ab_propose_schema():
    from three_surgeons.http.schemas import TOOL_SCHEMAS
    schema = TOOL_SCHEMAS["ab_propose"]
    validated = schema.model_validate({
        "param": "temperature",
        "variant_a": "0.7",
        "variant_b": "0.9",
        "hypothesis": "Higher temp improves creativity",
    })
    assert validated.param == "temperature"


def test_neurologist_challenge_schema():
    from three_surgeons.http.schemas import TOOL_SCHEMAS
    schema = TOOL_SCHEMAS["neurologist_challenge_tool"]
    validated = schema.model_validate({"topic": "test topic", "rounds": 2})
    assert validated.rounds == 2


def test_event_subscribe_schema():
    from three_surgeons.http.schemas import TOOL_SCHEMAS
    schema = TOOL_SCHEMAS["event_subscribe"]
    validated = schema.model_validate({"patterns": ["ide.*"]})
    assert validated.patterns == ["ide.*"]
