from fastapi import FastAPI, HTTPException, Request, Header
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response
from typing import List, Dict, Optional, Any
from pydantic import BaseModel
import logging
import time
import threading

from .models import AgentState, GenerateRequest, Status, HumanDecision, ReviewResponse
from .orchestrator import PipelineOrchestrator
from .config import settings
from .mcp_server import app as mcp_app
from .send_tools import send_email, send_linkedin_dm
from .graph import run_pipeline
from .memory import MemoryService
from .observability import prompt_store, init_runtime_config, get_runtime_config, pending_feedback as _pending_feedback
from mcp.server.sse import SseServerTransport

logging.basicConfig(level=getattr(logging, settings.LOG_LEVEL))
logger = logging.getLogger(__name__)

# Initialize RuntimeConfig singleton for global orchestrator overrides
_runtime_config = init_runtime_config(settings)

# Server start time for uptime tracking
_server_start_time = time.time()

# In-memory store for drafts awaiting human review — keyed by task_id
# Replace with Redis when you add persistence
_pending_review: Dict[str, AgentState] = {}

# ──────────────────────────────────────────────────────
# Idempotency Cache
# ──────────────────────────────────────────────────────
# In-memory cache for idempotency keys with per-key locking to prevent
# concurrent duplicate requests.
#
# KNOWN LIMITATION: This cache is in-memory and per-process. It will NOT
# deduplicate across multiple instances if the service is scaled horizontally.
# For multi-instance dedup, use Redis or another shared store.
#
# Cache structure:
# - _idempotency_cache: key -> (response, timestamp)
# - _idempotency_locks: key -> threading.Lock (per-key lock)
# - _idempotency_global_lock: protects _idempotency_locks dict itself

IDEMPOTENCY_TTL_SECONDS = 3600  # 1 hour
_idempotency_cache: Dict[str, tuple] = {}
_idempotency_locks: Dict[str, threading.Lock] = {}
_idempotency_global_lock = threading.Lock()


def _get_key_lock(idempotency_key: str) -> threading.Lock:
    """Get or create a lock for the given idempotency key."""
    with _idempotency_global_lock:
        if idempotency_key not in _idempotency_locks:
            _idempotency_locks[idempotency_key] = threading.Lock()
        return _idempotency_locks[idempotency_key]


def _get_cached_response(idempotency_key: Optional[str]) -> Optional[Dict[str, Any]]:
    """
    Return cached response if idempotency_key was seen recently, else None.
    
    NOTE: This is a quick check WITHOUT holding the per-key lock.
    The caller must use the per-key lock to prevent race conditions.
    """
    if not idempotency_key:
        return None
    entry = _idempotency_cache.get(idempotency_key)
    if entry is None:
        return None
    response, timestamp = entry
    if time.time() - timestamp > IDEMPOTENCY_TTL_SECONDS:
        # Expired — remove both cache entry AND lock (safe to do without lock, worst case double-delete)
        _idempotency_cache.pop(idempotency_key, None)
        _idempotency_locks.pop(idempotency_key, None)
        return None
    return response


def _cache_response(idempotency_key: Optional[str], response: Dict[str, Any]) -> None:
    """
    Cache the response for the given idempotency_key.
    
    NOTE: Caller must hold the per-key lock when calling this.
    """
    if not idempotency_key:
        return
    # Clean up expired entries if cache is getting large
    if len(_idempotency_cache) > 1000:
        now = time.time()
        expired_keys = [
            k for k, (_, ts) in _idempotency_cache.items()
            if now - ts > IDEMPOTENCY_TTL_SECONDS
        ]
        for k in expired_keys:
            _idempotency_cache.pop(k, None)
            _idempotency_locks.pop(k, None)
    _idempotency_cache[idempotency_key] = (response, time.time())


def _acquire_idempotency_lock(idempotency_key: str) -> threading.Lock:
    """Acquire the per-key lock for idempotency checking/caching."""
    key_lock = _get_key_lock(idempotency_key)
    key_lock.acquire()
    return key_lock


def _release_idempotency_lock(key_lock: threading.Lock) -> None:
    """Release the per-key idempotency lock."""
    key_lock.release()

app = FastAPI(
    title=settings.APP_NAME,
    version=settings.APP_VERSION,
    description="Multi-agent AI system for generating personalized outreach messages"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# MCP SSE transport — external agents connect to /mcp
sse_transport = SseServerTransport("/mcp/messages")


class _MCPApp:
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


@app.get("/")
async def root():
    return {
        "status": "online",
        "app": settings.APP_NAME,
        "version": settings.APP_VERSION,
        "environment": settings.ENVIRONMENT,
        "using_mock_data": settings.USE_MOCK_DATA
    }


@app.post("/api/generate", response_model=List[AgentState])
async def generate_outreach(request: GenerateRequest):
    """Full pipeline. Returns step-by-step history of agent states."""
    try:
        logger.info(
            f"Generating for {request.target_prospect} at {request.target_company} "
            f"| channel={request.channel} stage={request.stage} intent={request.intent}"
        )
        orchestrator = PipelineOrchestrator(
            target_prospect=request.target_prospect,
            target_company=request.target_company,
            prospect_role=request.prospect_role,
            channel=request.channel,
            intent=request.intent,
            stage=request.stage,
            personality=request.personality,
            company_details=request.company_details,
            selected_offer=request.selected_offer,
            research_signals=request.research_signals,
            user_feedback=request.user_feedback
        )
        history = orchestrator.run_full_pipeline()
        final = history[-1]
        logger.info(
            f"Done | status={final.status} "
            f"score={final.validation.score if final.validation else 'N/A'}"
        )
        return history
    except Exception as e:
        logger.error(f"Pipeline failed: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/generate/simple")
async def generate_simple(
    request: GenerateRequest,
    idempotency_key: Optional[str] = Header(None, alias="Idempotency-Key"),
):
    """
    Same pipeline but returns only the final message.

    Idempotency: If an Idempotency-Key header is provided, the response is cached
    for 1 hour. Retrying with the same key returns the cached response without
    re-running the pipeline.
    
    NOTE: The idempotency cache key is ONLY the Idempotency-Key header value.
    It does NOT incorporate the request body. Reusing the same key with different
    request bodies will return the cached response from the first request.
    """
    # Fast path: check cache without lock
    cached = _get_cached_response(idempotency_key)
    if cached is not None:
        return cached

    # Slow path: acquire per-key lock to prevent concurrent duplicates
    key_lock = None
    if idempotency_key:
        key_lock = _acquire_idempotency_lock(idempotency_key)
        # Re-check under lock (another thread might have cached while we waited)
        cached = _get_cached_response(idempotency_key)
        if cached is not None:
            _release_idempotency_lock(key_lock)
            return cached

    try:
        return await _run_generate_simple(request, idempotency_key, key_lock)
    finally:
        if key_lock:
            _release_idempotency_lock(key_lock)


async def _run_generate_simple(
    request: GenerateRequest,
    idempotency_key: Optional[str],
    key_lock: Optional[threading.Lock],
) -> Dict[str, Any]:
    """Run the message generation pipeline and cache the result."""
    try:
        orchestrator = PipelineOrchestrator(
            target_prospect=request.target_prospect,
            target_company=request.target_company,
            prospect_role=request.prospect_role,
            channel=request.channel,
            intent=request.intent,
            stage=request.stage,
            personality=request.personality,
            company_details=request.company_details,
            selected_offer=request.selected_offer,
            research_signals=request.research_signals,
            user_feedback=request.user_feedback
        )
        history = orchestrator.run_full_pipeline()
        final = history[-1]

        if final.status == Status.COMPLETE and final.draft:
            response = {
                "success": True,
                "task_id": final.task_id,
                "channel": final.channel,
                "stage": final.stage,
                "message": final.draft.body,
                "subject": final.draft.subject,
                "score": final.validation.score if final.validation else None,
                "warnings": final.validation.warnings if final.validation else [],
                "attribution": [a.dict() for a in final.draft.sentence_attribution]
            }
        elif final.status == Status.AWAITING_HUMAN and final.draft:
            # Park the state so the review endpoint can pick it up
            _pending_review[final.task_id] = final
            response = {
                "success": True,
                "awaiting_human": True,
                "task_id": final.task_id,
                "message": final.draft.body,
                "subject": final.draft.subject,
                "score": final.validation.score if final.validation else None,
                "warnings": final.validation.warnings if final.validation else [],
                "review_url": f"/api/review/{final.task_id}"
            }
        else:
            response = {
                "success": False,
                "task_id": final.task_id,
                "error": final.next_action.get("reason") if final.next_action else "Unknown error",
                "score": final.validation.score if final.validation else None,
                "warnings": final.validation.warnings if final.validation else []
            }

        # Cache the response for idempotency
        _cache_response(idempotency_key, response)

        return response
    except Exception as e:
        logger.error(f"Simple generation failed: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/reply")
async def record_reply(
    prospect_name: str,
    prospect_company: str,
    sentiment: str = "positive"
):
    """
    Call this when a prospect replies to a message.
    Updates prospect memory and feeds the learning system.
    sentiment: positive | negative | neutral
    """
    MemoryService.prospects.mark_replied(
        name=prospect_name,
        company=prospect_company,
        sentiment=sentiment
    )
    return {"success": True, "message": f"Reply recorded for {prospect_name} at {prospect_company}"}


@app.get("/api/review/{task_id}", response_model=ReviewResponse)
async def get_review(task_id: str):
    """Get the draft waiting for human approval."""
    state = _pending_review.get(task_id)
    if not state:
        raise HTTPException(status_code=404, detail="No draft pending review for this task_id")
    return ReviewResponse(
        task_id=state.task_id,
        prospect=state.target_prospect,
        company=state.target_company,
        channel=state.channel.value,
        message=state.draft.body,
        subject=state.draft.subject,
        score=state.validation.score if state.validation else 0,
        warnings=state.validation.warnings if state.validation else [],
    )


@app.post("/api/review/{task_id}/decision")
async def submit_decision(task_id: str, decision: HumanDecision):
    """
    Approve → send via email or LinkedIn.
    Reject  → rerun writer with your feedback.
    """
    state = _pending_review.get(task_id)
    if not state:
        raise HTTPException(status_code=404, detail="No draft pending review for this task_id")

    if decision.approved:
        channel = state.channel.value
        message = state.draft.body
        subject = state.draft.subject or ""

        if channel == "email":
            if not decision.prospect_email:
                raise HTTPException(status_code=400, detail="prospect_email is required for email channel")
            result = send_email(to_address=decision.prospect_email, subject=subject, body=message)

        elif channel in ("linkedin_dm", "linkedin_inmail"):
            if not decision.prospect_linkedin_id:
                raise HTTPException(status_code=400, detail="prospect_linkedin_id is required for LinkedIn channel")
            result = send_linkedin_dm(
                account_id=settings.UNIPILE_DEFAULT_ACCOUNT_ID or "",
                message=message,
                attendee_provider_id=decision.prospect_linkedin_id,
                attendee_name=state.target_prospect,
            )
        else:
            result = {"success": True, "channel": channel, "note": "Manual send required for this channel"}

        if result.get("success"):
            state.status = Status.COMPLETE
            _pending_review.pop(task_id, None)
            return {"success": True, "sent": True, "result": result}
        else:
            raise HTTPException(status_code=500, detail=f"Send failed: {result.get('error')}")

    else:
        feedback = decision.feedback or "Human reviewer rejected this draft. Please rewrite it."
        state.status = Status.REVISING
        state.iteration_count += 1
        state.next_action = {"type": "retry", "reason": "Rejected by human reviewer", "feedback": feedback}
        _pending_review.pop(task_id, None)

        history = run_pipeline(state)
        final = history[-1]

        if final.status == Status.AWAITING_HUMAN and final.draft:
            _pending_review[final.task_id] = final
            return {
                "success": True,
                "rewritten": True,
                "awaiting_human": True,
                "task_id": final.task_id,
                "message": final.draft.body,
                "subject": final.draft.subject,
                "score": final.validation.score if final.validation else None,
                "review_url": f"/api/review/{final.task_id}",
            }
        elif final.status == Status.COMPLETE and final.draft:
            return {"success": True, "rewritten": True, "message": final.draft.body}
        else:
            return {"success": False, "error": final.next_action.get("reason") if final.next_action else "Rewrite failed"}


@app.post("/api/send/email")
async def send_email_api(
    to_address: str,
    subject: str,
    body: str
):
    """
    Direct API to send an email via Gmail SMTP.
    Sequence generator can call this to send messages.
    """
    result = send_email(to_address=to_address, subject=subject, body=body)
    
    if result.get("success"):
        return {
            "success": True,
            "sent": True,
            "to": result.get("to"),
            "channel": result.get("channel")
        }
    else:
        raise HTTPException(status_code=500, detail=f"Send failed: {result.get('error')}")


# ── Memory Management ──────────────────────────────────────────────

@app.get("/api/memory/status")
async def memory_status():
    """
    See what's currently stored in memory.
    Returns debug_mode flag, backend type, counts, and learning stats.
    """
    return MemoryService.status()


@app.post("/api/memory/flush")
async def memory_flush():
    """
    Wipe ALL stored memory (prospect, learning, offer).
    Use during debugging to reset state between test runs.
    Returns a summary of what was deleted.
    """
    deleted = MemoryService.flush()
    return {"success": True, "deleted": deleted}


# ── Observability (for Outreach Orchestrator / Global Orchestrator) ──────

@app.get("/api/observability")
async def get_observability():
    """
    Aggregated observability metrics from the Message Generator.
    Returns token usage, LLM call counts, quality scores, model info, uptime.
    """
    obs_summary = prompt_store.get_summary()
    rc = get_runtime_config()
    return {
        "module": "message_generator",
        "total_tokens": obs_summary.get("total_tokens", 0),
        "total_tokens_in": obs_summary.get("total_tokens_in", 0),
        "total_tokens_out": obs_summary.get("total_tokens_out", 0),
        "total_llm_calls": obs_summary.get("total_calls", 0),
        "calls_by_agent": obs_summary.get("calls_by_agent", {}),
        "success_rate": obs_summary.get("success_rate", 0.0),
        "avg_latency_ms": obs_summary.get("avg_latency_ms", 0.0),
        "model": rc.get("GEMINI_MODEL", settings.GEMINI_MODEL),
        "fallback_model": settings.GEMINI_FALLBACK_MODEL,
        "temperature": rc.get("GEMINI_TEMPERATURE", settings.GEMINI_TEMPERATURE),
        "max_iterations": rc.get("MAX_ITERATIONS", settings.MAX_ITERATIONS),
        "min_quality_score": rc.get("MIN_QUALITY_SCORE", settings.MIN_QUALITY_SCORE),
        "uptime_seconds": round(time.time() - _server_start_time, 1),
        "pending_feedback_count": len(_pending_feedback),
        "config_overrides": rc.get_all_overrides(),
    }


@app.get("/api/observability/prompts")
async def get_prompt_history(limit: int = 50, agent_step: Optional[str] = None):
    """
    Returns prompt history — actual prompts sent to LLM, responses, tokens, latency.
    Filterable by agent_step (researcher, strategist, writer, critic).
    """
    return prompt_store.get_history(limit=limit, agent_step=agent_step)


class ConfigOverrideRequest(BaseModel):
    overrides: Dict[str, Any]


@app.post("/api/config/override")
async def override_config(req: ConfigOverrideRequest):
    """
    Override runtime settings (MAX_ITERATIONS, GEMINI_TEMPERATURE, MIN_QUALITY_SCORE, etc.).
    Only whitelisted keys are accepted. Unknown keys are rejected.
    """
    rc = get_runtime_config()
    accepted = {}
    rejected = {}
    for key, value in req.overrides.items():
        if rc.set(key, value):
            accepted[key] = value
        else:
            rejected[key] = "not in allowed override keys"
    return {
        "success": len(rejected) == 0,
        "accepted": accepted,
        "rejected": rejected,
        "current_overrides": rc.get_all_overrides(),
    }


@app.post("/api/config/reset")
async def reset_config():
    """Reset all runtime config overrides to defaults."""
    rc = get_runtime_config()
    rc.reset()
    return {"success": True, "message": "All overrides cleared"}


class FeedbackRequest(BaseModel):
    feedback: str


@app.post("/api/feedback")
async def inject_feedback(req: FeedbackRequest):
    """
    Inject feedback from the global orchestrator.
    The feedback is prepended to the next writer/critic prompt as a system directive.
    This is a one-time influence — re-inject to persist.
    """
    _pending_feedback.append(req.feedback)
    logger.info(f"Feedback injected: {req.feedback[:100]}...")
    return {
        "success": True,
        "pending_feedback_count": len(_pending_feedback),
        "message": "Feedback will be prepended to next writer/critic prompt",
    }


@app.post("/api/observability/clear")
async def clear_prompt_history():
    """Clear prompt history."""
    count = prompt_store.clear()
    return {"success": True, "cleared": count}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        app,
        host=settings.HOST,
        port=settings.PORT,
        log_level=settings.LOG_LEVEL.lower()
    )
