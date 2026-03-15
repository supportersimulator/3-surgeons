"""Pydantic v2 request schemas for Layer 2 REST API."""
from __future__ import annotations

from typing import Dict, List, Literal, Optional, Type

from pydantic import BaseModel, Field


class ProbeRequest(BaseModel):
    """No params needed for health probe."""
    pass


class CrossExamineRequest(BaseModel):
    topic: str = Field(..., min_length=1, description="Topic to cross-examine")
    depth: Literal["full", "quick", "deep"] = Field(
        default="full", description="Analysis depth"
    )
    mode: Literal["single", "iterative", "continuous"] = Field(
        default="single", description="Review iteration mode"
    )
    file_paths: Optional[List[str]] = Field(
        default=None, description="Source files for context"
    )


class ConsultRequest(BaseModel):
    topic: str = Field(..., min_length=1, description="Topic to consult on")
    file_paths: Optional[List[str]] = Field(
        default=None, description="Source files for context"
    )


class ConsensusRequest(BaseModel):
    claim: str = Field(..., min_length=1, description="Claim to evaluate")


class CapStatusRequest(BaseModel):
    """No params needed for status."""
    pass


class CapResearchStatusRequest(BaseModel):
    """No params needed for research status."""
    pass


class CapAbVetoRequest(BaseModel):
    test_id: str = Field(..., min_length=1, description="A/B test ID to veto")
    reason: str = Field(..., min_length=1, description="Reason for veto")


class CapAbQueueRequest(BaseModel):
    """No params needed for queue listing."""
    pass


class CapAbStartRequest(BaseModel):
    test_id: str = Field(..., min_length=1, description="A/B test ID to start")
    duration_minutes: Optional[int] = Field(default=30, description="Duration in minutes")


class CapAbMeasureRequest(BaseModel):
    test_id: str = Field(..., min_length=1, description="A/B test ID to measure")


class CapAbConcludeRequest(BaseModel):
    test_id: str = Field(..., min_length=1, description="A/B test ID to conclude")
    verdict: str = Field(..., min_length=1, description="Verdict")


class CapAbCollaborateRequest(BaseModel):
    topic: str = Field(..., min_length=1, description="Topic for multi-surgeon collaboration")


class CapResearchEvidenceRequest(BaseModel):
    topic: str = Field(..., min_length=1, description="Topic to cross-check evidence for")


class CapCardioReverifyRequest(BaseModel):
    topic: str = Field(..., min_length=1, description="Topic to reverify")


class CapDeepAuditRequest(BaseModel):
    topic: str = Field(..., min_length=1, description="Topic for deep audit")


class SentinelRunRequest(BaseModel):
    content: str = Field(..., min_length=1, description="Content to scan for complexity")


class GainsGateRequest(BaseModel):
    """No params needed."""
    pass


class AbProposeRequest(BaseModel):
    param: str = Field(..., min_length=1, description="Parameter to test")
    variant_a: str = Field(..., description="Variant A value")
    variant_b: str = Field(..., description="Variant B value")
    hypothesis: str = Field(..., min_length=1, description="Test hypothesis")


class AbStartRequest(BaseModel):
    test_id: str = Field(..., min_length=1, description="A/B test ID")


class AbMeasureRequest(BaseModel):
    test_id: str = Field(..., min_length=1, description="A/B test ID")
    metric_a: float = Field(..., description="Metric value for variant A")
    metric_b: float = Field(..., description="Metric value for variant B")


class AbConcludeRequest(BaseModel):
    test_id: str = Field(..., min_length=1, description="A/B test ID")
    verdict: str = Field(..., description="Test verdict")


class AbValidateRequest(BaseModel):
    description: str = Field(..., min_length=1, description="Fix description to validate")


class AskLocalRequest(BaseModel):
    prompt: str = Field(..., min_length=1, description="Prompt for neurologist")


class AskRemoteRequest(BaseModel):
    prompt: str = Field(..., min_length=1, description="Prompt for cardiologist")


class NeurologistPulseRequest(BaseModel):
    """No params needed."""
    pass


class NeurologistChallengeRequest(BaseModel):
    topic: str = Field(..., min_length=1, description="Topic to challenge")
    file_paths: Optional[List[str]] = Field(default=None, description="Source files")
    rounds: int = Field(default=1, ge=1, le=5, description="Challenge rounds")


class IntrospectRequest(BaseModel):
    """No params needed."""
    pass


class CardioReviewRequest(BaseModel):
    topic: str = Field(..., min_length=1, description="Review topic")
    git_context: Optional[str] = Field(default=None, description="Git diff or context")
    file_paths: Optional[List[str]] = Field(default=None, description="Source files")


class ResearchRequest(BaseModel):
    topic: str = Field(..., min_length=1, description="Research topic")


class UpgradeProbeRequest(BaseModel):
    """No params needed."""
    pass


class UpgradeHistoryRequest(BaseModel):
    """No params needed."""
    pass


class EventSubscribeRequest(BaseModel):
    patterns: List[str] = Field(..., min_length=1, description="Event patterns to subscribe to")


class EventUnsubscribeRequest(BaseModel):
    stream_id: str = Field(..., min_length=1, description="Stream ID to unsubscribe")


class EventPublishRequest(BaseModel):
    event_type: str = Field(..., min_length=1, description="Event type")
    payload: Optional[Dict] = Field(default=None, description="Event payload")
    correlation_id: Optional[str] = Field(default=None, description="Correlation ID")


class EventPollRequest(BaseModel):
    stream_id: str = Field(..., min_length=1, description="Stream ID to poll")


# Registry: tool name → schema class
TOOL_SCHEMAS: dict[str, Type[BaseModel]] = {
    "probe": ProbeRequest,
    "cross_examine": CrossExamineRequest,
    "consult": ConsultRequest,
    "consensus": ConsensusRequest,
    "cap_status": CapStatusRequest,
    "cap_research_status": CapResearchStatusRequest,
    "cap_ab_veto": CapAbVetoRequest,
    "cap_ab_queue": CapAbQueueRequest,
    "cap_ab_start": CapAbStartRequest,
    "cap_ab_measure": CapAbMeasureRequest,
    "cap_ab_conclude": CapAbConcludeRequest,
    "cap_ab_collaborate": CapAbCollaborateRequest,
    "cap_research_evidence": CapResearchEvidenceRequest,
    "cap_cardio_reverify": CapCardioReverifyRequest,
    "cap_deep_audit": CapDeepAuditRequest,
    "sentinel_run": SentinelRunRequest,
    "gains_gate": GainsGateRequest,
    "ab_propose": AbProposeRequest,
    "ab_start": AbStartRequest,
    "ab_measure": AbMeasureRequest,
    "ab_conclude": AbConcludeRequest,
    "ab_validate_tool": AbValidateRequest,
    "ask_local_tool": AskLocalRequest,
    "ask_remote_tool": AskRemoteRequest,
    "neurologist_pulse_tool": NeurologistPulseRequest,
    "neurologist_challenge_tool": NeurologistChallengeRequest,
    "introspect_tool": IntrospectRequest,
    "cardio_review_tool": CardioReviewRequest,
    "research_tool": ResearchRequest,
    "upgrade_probe": UpgradeProbeRequest,
    "upgrade_history": UpgradeHistoryRequest,
    "event_subscribe": EventSubscribeRequest,
    "event_unsubscribe": EventUnsubscribeRequest,
    "event_publish": EventPublishRequest,
    "event_poll": EventPollRequest,
}
