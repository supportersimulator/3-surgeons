"""Pydantic v2 request schemas for Layer 2 REST API."""
from __future__ import annotations

from typing import List, Literal, Optional, Type

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
}
