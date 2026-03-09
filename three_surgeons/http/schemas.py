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


# Registry: tool name → schema class
TOOL_SCHEMAS: dict[str, Type[BaseModel]] = {
    "probe": ProbeRequest,
    "cross_examine": CrossExamineRequest,
    "consult": ConsultRequest,
    "consensus": ConsensusRequest,
}
