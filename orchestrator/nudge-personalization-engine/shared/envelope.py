"""Standardized response envelope pattern for all module-to-module communication."""

import uuid
from typing import Any, Dict, Literal, Optional
from pydantic import BaseModel, Field


class ResponseEnvelope(BaseModel):
    """Standard response wrapper for all API responses."""
    task_id: str = Field(default_factory=lambda: str(uuid.uuid4()), description="Unique task identifier")
    source_agent: str = Field(..., description="Name of the agent/service generating this response")
    status: Literal["success", "failed", "needs_clarification"] = Field(..., description="Response status")
    payload: Any = Field(default=None, description="Response data")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="Additional metadata")


def ok(
    source: str,
    payload: Any,
    metadata: Optional[Dict[str, Any]] = None,
    task_id: Optional[str] = None
) -> Dict[str, Any]:
    """Create a success response envelope."""
    return ResponseEnvelope(
        task_id=task_id or str(uuid.uuid4()),
        source_agent=source,
        status="success",
        payload=payload,
        metadata=metadata or {}
    ).model_dump()


def fail(
    source: str,
    error: str,
    task_id: Optional[str] = None
) -> Dict[str, Any]:
    """Create a failure response envelope."""
    return ResponseEnvelope(
        task_id=task_id or str(uuid.uuid4()),
        source_agent=source,
        status="failed",
        payload={"error": error},
        metadata={}
    ).model_dump()


def clarify(
    source: str,
    reason: str,
    task_id: Optional[str] = None
) -> Dict[str, Any]:
    """Create a clarification-required response envelope."""
    return ResponseEnvelope(
        task_id=task_id or str(uuid.uuid4()),
        source_agent=source,
        status="needs_clarification",
        payload={"reason": reason},
        metadata={}
    ).model_dump()
