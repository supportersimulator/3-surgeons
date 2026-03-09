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
