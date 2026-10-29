"""
Outreach Orchestrator — FastAPI server (port 8002).

Coordinates Sequence Generator and Message Generator, exposes:
- REST API for direct access
- MCP server for global orchestrator connections
- Observability endpoints

Run:
    cd "outreach orchestrator"
    python -m uvicorn app.main:app --host 0.0.0.0 --port 8002 --reload
"""

import logging
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from typing import Dict, Any, Optional, List
from pydantic import BaseModel

from .config import settings
from .state import OrchestratorState
from .graph import run_orchestrator
from .clients import SequenceGeneratorClient, MessageGeneratorClient
from .observability import ObservabilityAggregator
from .mcp_server import app as mcp_app
from mcp.server.sse import SseServerTransport

logging.basicConfig(level=getattr(logging, settings.LOG_LEVEL))
logger = logging.getLogger(__name__)

app = FastAPI(
    title=settings.APP_NAME,
    version=settings.APP_VERSION,
    description="Hierarchical orchestrator coordinating Sequence Generator + Message Generator, with MCP interface for global orchestrator",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# MCP SSE transport — global orchestrator connects here
sse_transport = SseServerTransport("/mcp/messages")


class _MCPApp:
    """Raw ASGI app that routes GET/POST to the SSE transport.

    This matches the MCP SDK's intended usage pattern (see mcp.server.sse docstring):
    Mount the transport directly rather than wrapping in FastAPI route handlers,
    which avoids the double-response problem.
    """

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return
        if scope["method"] == "GET":
            async with sse_transport.connect_sse(scope, receive, send) as streams:
                await mcp_app.run(
                    streams[0], streams[1], mcp_app.create_initialization_options()
                )
        elif scope["method"] == "POST":
            await sse_transport.handle_post_message(scope, receive, send)


app.mount("/mcp", _MCPApp())

# Shared clients and aggregator
_seq_client = SequenceGeneratorClient()
_msg_client = MessageGeneratorClient()
_aggregator = ObservabilityAggregator(_seq_client, _msg_client)


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------

@app.get("/")
async def root():
    return {
        "status": "online",
        "app": settings.APP_NAME,
        "version": settings.APP_VERSION,
        "environment": settings.ENVIRONMENT,
        "modules": {
            "sequence_generator": settings.SEQUENCE_GENERATOR_URL,
            "message_generator": settings.MESSAGE_GENERATOR_URL,
        },
    }


# ---------------------------------------------------------------------------
# REST API — Pipeline
# ---------------------------------------------------------------------------

class RunPipelineRequest(BaseModel):
    lead_id: str = ""
    campaign_id: str = "default_campaign"
    entreprise: str
    contact_info: Dict[str, Any] = {}
    contexte_web: Dict[str, Any] = {}
    research_signals: Optional[List[Dict[str, Any]]] = None
    is_connected_on_linkedin: bool = False
    has_inmail_credits: bool = False  # LinkedIn InMail credits (Sales Navigator / premium)
    use_native_language: bool = False
    message_language: Optional[str] = None
    approval_mode: str = "per_sequence"
    sender_company: str = "My Company"
    sender_elevator_pitch: str = ""
    offer_name: str = "Default Offer"
    solution_summary: str = ""
    cta: str = ""
    # ── AI Sequence Configuration ──
    max_touches: Optional[int] = None
    max_days: Optional[int] = None
    preferred_first_channel: Optional[str] = None
    sequence_options: Optional[Dict[str, bool]] = None
    stage_instructions: Optional[Dict[str, str]] = None
    # ── Personality Configuration (forwarded to Message Generator via Sequence Generator) ──
    personality_config: Optional[Dict[str, Any]] = None
    feedback: Optional[str] = None
    config_overrides: Optional[Dict[str, Any]] = None
    debug_mode: bool = True  # Propagated to modules: bypass memory for deterministic runs


@app.post("/api/run")
async def run_pipeline(req: RunPipelineRequest):
    """Run the full outreach pipeline via the orchestrator."""
    try:
        state = OrchestratorState(**req.model_dump())
        result = await run_orchestrator(state)
        return result
    except Exception as e:
        logger.error(f"Pipeline failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


class ApprovePipelineRequest(BaseModel):
    approved: bool = True
    feedback: Optional[str] = None


@app.post("/api/approve/{thread_id}")
async def approve_pipeline(thread_id: str, req: ApprovePipelineRequest):
    """
    Approve or reject a paused sequence, forwarding to the Sequence Generator.

    The orchestrator owns zero approval state — it passes through to the
    Sequence Generator's /api/approve/{thread_id} endpoint.
    """
    try:
        result = await _seq_client.approve_sequence(
            thread_id=thread_id,
            approved=req.approved,
            feedback=req.feedback,
        )
        return result
    except Exception as e:
        logger.error(f"Approve failed for {thread_id}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


# ---------------------------------------------------------------------------
# REST API — Observability
# ---------------------------------------------------------------------------

@app.get("/api/observability")
async def get_observability():
    """Aggregated observability from both modules."""
    try:
        return await _aggregator.collect_full_snapshot()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/observability/prompts")
async def get_prompt_history(
    module: Optional[str] = None,
    agent_step: Optional[str] = None,
    limit: int = 50,
):
    """Prompt history from one or both modules."""
    try:
        return await _aggregator.get_prompt_history(
            module=module, agent_step=agent_step, limit=limit
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/health")
async def check_health():
    """Health check for both downstream modules."""
    return await _aggregator.check_health()


# ---------------------------------------------------------------------------
# REST API — Config + Feedback
# ---------------------------------------------------------------------------

class ConfigOverrideRequest(BaseModel):
    module: str
    overrides: Dict[str, Any]


@app.post("/api/config/override")
async def override_config(req: ConfigOverrideRequest):
    """Override config on a specific module."""
    try:
        return await _aggregator.override_config(req.module, req.overrides)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


class ConfigResetRequest(BaseModel):
    module: str


@app.post("/api/config/reset")
async def reset_config(req: ConfigResetRequest):
    """Reset config overrides on a specific module."""
    try:
        return await _aggregator.reset_config(req.module)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


class FeedbackRequest(BaseModel):
    module: str
    feedback: str


@app.post("/api/feedback")
async def inject_feedback(req: FeedbackRequest):
    """Inject feedback to a specific module."""
    try:
        return await _aggregator.inject_feedback(req.module, req.feedback)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/capabilities")
async def get_capabilities():
    """Agent card — what this system can do."""
    return {
        "system_name": "Outreach Orchestrator",
        "version": settings.APP_VERSION,
        "supported_channels": ["email", "linkedin_dm", "linkedin_inmail"],
        "mcp_tools": [
            "run_outreach_pipeline",
            "approve_pipeline",
            "get_outreach_status",
            "get_observability",
            "get_prompt_history",
            "override_module_config",
            "inject_feedback",
            "get_module_capabilities",
        ],
        "modules": {
            "sequence_generator": settings.SEQUENCE_GENERATOR_URL,
            "message_generator": settings.MESSAGE_GENERATOR_URL,
        },
    }


# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        app,
        host=settings.HOST,
        port=settings.PORT,
        log_level=settings.LOG_LEVEL.lower(),
    )
