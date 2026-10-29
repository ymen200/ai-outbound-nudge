"""
FastAPI REST API for the Sequence Generator.

Run:
    cd "sequence generator"
    pip install fastapi uvicorn
    python -m uvicorn scripts.api_server:app --host 0.0.0.0 --port 8001 --reload

Then:
    POST http://localhost:8001/api/generate/sequence
    Swagger UI: http://localhost:8001/docs
"""

import io
import os
import sys
import time
import uuid
import json
import importlib
import importlib.util
import threading
from pathlib import Path
from typing import Dict, Any, Optional, List
from datetime import datetime, timedelta, timezone

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Header, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from langgraph.checkpoint.memory import MemorySaver

# Force UTF-8 on Windows terminals
if os.name == "nt":
    os.environ["PYTHONIOENCODING"] = "utf-8"
    try:
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    except Exception:
        pass

# ── Package Registration ──
# The directory "sequence generator" has a space, so we register it as
# the importable package "sequence_generator" via importlib.

SCRIPT_DIR = Path(__file__).resolve().parent
SEQ_GEN_DIR = SCRIPT_DIR.parent
sys.path.insert(0, str(SEQ_GEN_DIR))


def _load_pkg_module(pkg_name: str, pkg_dir: Path):
    init_file = pkg_dir / "__init__.py"
    if not init_file.exists():
        init_file.write_text("# auto-generated for package registration\n")
    spec = importlib.util.spec_from_file_location(
        pkg_name, str(init_file),
        submodule_search_locations=[str(pkg_dir)]
    )
    mod = importlib.util.module_from_spec(spec)
    sys.modules[pkg_name] = mod
    spec.loader.exec_module(mod)
    return mod


_seq_gen = _load_pkg_module("sequence_generator", SEQ_GEN_DIR)

for subpkg in ["config", "models", "graph", "graph.nodes", "tools",
               "observability", "temporal", "workflows", "middleware"]:
    subpkg_path = SEQ_GEN_DIR / subpkg.replace(".", "/")
    if subpkg_path.is_dir():
        full_name = f"sequence_generator.{subpkg}"
        init = subpkg_path / "__init__.py"
        if not init.exists():
            init.write_text("")
        try:
            spec = importlib.util.spec_from_file_location(
                full_name, str(init),
                submodule_search_locations=[str(subpkg_path)]
            )
            if spec and spec.loader:
                mod = importlib.util.module_from_spec(spec)
                sys.modules[full_name] = mod
                spec.loader.exec_module(mod)
        except Exception:
            pass

load_dotenv(SEQ_GEN_DIR / ".env")

from sequence_generator.graph.state import GraphState
from sequence_generator.graph.builder import create_graph, _build_workflow
from sequence_generator.models.outreach_step import OutreachSequence
from sequence_generator.observability.observability_store import (
    prompt_store as seq_prompt_store,
    runtime_config as seq_runtime_config,
)
from sequence_generator.graph.nodes.sequence_generator_node import _pending_feedback as seq_pending_feedback


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


# ──────────────────────────────────────────────────────
# Request / Response Models
# ──────────────────────────────────────────────────────

class ContactInfo(BaseModel):
    full_name: str = Field(..., description="Prospect's full name")
    job_title: str = Field("", description="Prospect's job title / role")
    email: str = Field("", description="Prospect's email address")
    country: str = Field("", description="Country (used for timezone + language detection)")
    city: str = Field("", description="City")
    location: str = Field("", description="Full location string, e.g. 'Tunis, Tunisia'")
    phone: str = Field("", description="Phone number")
    linkedin: str = Field("", description="LinkedIn profile URL")
    is_connected_on_linkedin: bool = Field(
        False,
        description="Whether you are already connected with this prospect on LinkedIn. "
                    "If False, the first LinkedIn step will be a connection request (LINKEDIN_CONNECT). "
                    "If True, messages can be sent directly (LINKEDIN_MESSAGE)."
    )
    has_inmail_credits: bool = Field(
        False,
        description="Whether the sender has LinkedIn InMail credits (Sales Navigator / premium). "
                    "When True AND is_connected_on_linkedin is False, Gemini may use LINKEDIN_INMAIL "
                    "(channel: linkedin_inmail) for the first LinkedIn step instead of LINKEDIN_CONNECT."
    )


class WebContext(BaseModel):
    profil_brut: str = Field("", description="Raw web profile / research summary about the prospect")
    offer_context: str = Field("", description="Description of the offer being pitched")
    icp_description: str = Field("", description="Ideal customer profile description")


class CompanyInfo(BaseModel):
    company_name: str = Field(..., description="Sender's company name")
    elevator_pitch: str = Field("", description="Sender's company elevator pitch")
    offer_name: str = Field("Default Offer", description="Name of the offer being pitched")
    solution_summary: str = Field("", description="Brief description of the solution")
    cta: str = Field("", description="Call-to-action text")


class GenerateSequenceRequest(BaseModel):
    lead_id: str = Field(default="", description="Unique lead ID (auto-generated if empty)")
    campaign_id: str = Field(default="default_campaign", description="Campaign identifier")
    company: str = Field(..., description="Prospect's company name")
    contact: ContactInfo
    web_context: WebContext = Field(default_factory=WebContext)
    sender_info: CompanyInfo = Field(
        default_factory=lambda: CompanyInfo(company_name="My Company")
    )
    approval_mode: str = Field(
        "per_sequence",
        description="Approval mode: per_sequence, per_step, or per_step_and_message"
    )
    use_native_language: bool = Field(
        False,
        description=(
            "If True, messages are generated in the prospect's detected language. "
            "If False, messages are in English. Explanations are always English."
        )
    )
    message_language: Optional[str] = Field(
        None,
        description=(
            "Explicit ISO 639-1 language code to override auto-detected language "
            "(e.g., 'fr', 'es', 'de'). When set, use_native_language is forced True."
        )
    )
    research_signals: Optional[List[Dict[str, Any]]] = Field(
        None,
        description=(
            "Pre-fetched research signals from upstream modules (Detective). "
            "Each signal: {type, content, strength, source_url?, timestamp?, why_relevant}. "
            "Forwarded to the Message Generator for personalized message generation."
        )
    )

    # ── AI Sequence Configuration (user overrides) ──
    max_touches: Optional[int] = Field(
        None,
        description="Maximum number of touches in the sequence. Leave None for AI to decide."
    )
    max_days: Optional[int] = Field(
        None,
        description="Maximum days the sequence can span. Leave None for AI to decide."
    )
    preferred_first_channel: Optional[str] = Field(
        None,
        description="Preferred channel for the first touch (email, linkedin_dm, linkedin_inmail). AI decides if omitted."
    )
    sequence_options: Optional[Dict[str, bool]] = Field(
        None,
        description=(
            "Boolean flags controlling sequence behavior: "
            "vary_tone, include_breakup, reference_previous, escalate_urgency, cross_channel"
        )
    )
    stage_instructions: Optional[Dict[str, str]] = Field(
        None,
        description="Per-stage custom instructions for AI behavior, e.g. {'first_touch': 'Be casual, no pitch'}"
    )

    # ── Human Feedback (User Notes) ──
    user_feedback: Optional[str] = Field(
        None,
        description="Human feedback/notes to guide sequence generation. Injected into the prompt as 'user notes: '."
    )

    # ── Personality Configuration ──
    personality_config: Optional[Dict[str, Any]] = Field(
        None,
        description=(
            "Personality/style configuration forwarded to the Message Generator. "
            "Keys match the Personality model: base_template, personality_traits, "
            "always_include_phrases, never_use_phrases, urgency_level, humor_sarcasm, "
            "voice_samples, stage_instructions, etc."
        )
    )


class StepResult(BaseModel):
    step_number: int
    action_type: str
    channel: str
    scheduled_timestamp_utc: str
    scheduled_timestamp_local: Optional[str] = None
    local_timezone: Optional[str] = None
    wait_delay_seconds: int
    wait_delay_human: str
    message_language: Optional[str] = None
    timing_justification: str
    rationale: str
    message: Optional[str] = None
    subject: Optional[str] = None
    message_score: Optional[int] = None
    message_error: Optional[str] = None


class GenerateSequenceResponse(BaseModel):
    status: str
    thread_id: Optional[str] = None
    lead_id: str
    campaign_id: str
    detected_language: Optional[str] = None
    detected_language_name: Optional[str] = None
    detected_timezone: Optional[str] = None
    use_native_language: bool
    approval_mode: str
    total_steps: int
    steps: List[StepResult]
    sandbox_adjustments: List[Dict[str, Any]] = []
    message_generation_summary: Dict[str, int] = {}
    generation_time_seconds: float = 0.0
    errors: List[str] = []


class ApproveSequenceRequest(BaseModel):
    approved: bool = Field(..., description="Whether to approve (true) or reject (false) the sequence")
    user_feedback: Optional[str] = Field(None, description="Human feedback/notes. If rejecting, this will be used for regeneration.")


# ──────────────────────────────────────────────────────
# App Setup
# ──────────────────────────────────────────────────────

app = FastAPI(
    title="Sequence Generator API",
    description=(
        "Generate outreach sequences with timezone-aware scheduling, "
        "language detection, and JIT message generation."
    ),
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

_graph_app = None
_graph_memory = None
_graph_app_lock = threading.Lock()


def get_graph_app():
    """Get the singleton graph app + shared MemorySaver. Thread-safe lazy init."""
    global _graph_app, _graph_memory
    if _graph_app is None:
        with _graph_app_lock:
            if _graph_app is None:
                _graph_memory = MemorySaver()
                # Compile graph with the shared checkpointer so state persists across requests
                workflow = _build_workflow()
                _graph_app = workflow.compile(
                    checkpointer=_graph_memory,
                    interrupt_before=["dispatch_to_temporal"]
                )
    return _graph_app, _graph_memory


def _format_wait_delay(seconds: int) -> str:
    if seconds < 3600:
        return f"{seconds // 60}m"
    elif seconds < 86400:
        return f"{seconds / 3600:.1f}h"
    else:
        return f"{seconds / 86400:.1f}d"


# ──────────────────────────────────────────────────────
# Endpoints
# ──────────────────────────────────────────────────────

@app.post("/api/generate/sequence", response_model=GenerateSequenceResponse)
async def generate_sequence_endpoint(
    req: GenerateSequenceRequest,
    idempotency_key: Optional[str] = Header(None, alias="Idempotency-Key"),
):
    """
    Generate an outreach sequence for a prospect.

    Runs the full pipeline:
    1. Language & timezone detection from prospect's country
    2. Gemini-powered sequence strategy generation
    3. Sandbox enforcement (prospect-local business hours)
    4. JIT message generation per step (calls message generator API if running)

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
        return GenerateSequenceResponse(**cached)

    # Slow path: acquire per-key lock to prevent concurrent duplicates
    key_lock = None
    if idempotency_key:
        key_lock = _acquire_idempotency_lock(idempotency_key)
        # Re-check under lock (another thread might have cached while we waited)
        cached = _get_cached_response(idempotency_key)
        if cached is not None:
            _release_idempotency_lock(key_lock)
            return GenerateSequenceResponse(**cached)

    try:
        return await _run_generate_sequence(req, idempotency_key, key_lock)
    finally:
        if key_lock:
            _release_idempotency_lock(key_lock)


async def _run_generate_sequence(
    req: GenerateSequenceRequest,
    idempotency_key: Optional[str],
    key_lock: Optional[threading.Lock],
) -> GenerateSequenceResponse:
    """Run the sequence generation pipeline and cache the result."""
    start_time = time.time()
    lead_id = req.lead_id or f"lead_{uuid.uuid4().hex[:8]}"

    contact_info = {
        "nom": req.contact.full_name,
        "full_name": req.contact.full_name,
        "titre": req.contact.job_title,
        "job_title": req.contact.job_title,
        "email": req.contact.email,
        "country": req.contact.country,
        "city": req.contact.city,
        "location": req.contact.location or f"{req.contact.city}, {req.contact.country}".strip(", "),
        "phone": req.contact.phone,
        "linkedin": req.contact.linkedin,
    }

    contexte_web = {
        "profil_brut": req.web_context.profil_brut,
        "offer_context": req.web_context.offer_context,
        "icp_description": req.web_context.icp_description,
        "sender_company": req.sender_info.company_name,
        "elevator_pitch": req.sender_info.elevator_pitch,
        "offer_name": req.sender_info.offer_name,
        "solution_summary": req.sender_info.solution_summary,
        "cta": req.sender_info.cta,
    }

    # If explicit message_language is set, force native language mode
    use_native = req.use_native_language
    if req.message_language:
        use_native = True

    initial_state = GraphState(
        lead_id=lead_id,
        campaign_id=req.campaign_id,
        entreprise=req.company,
        contact_info=contact_info,
        contexte_web=contexte_web,
        approval_mode=req.approval_mode,
        use_native_language=use_native,
        message_language=req.message_language,
        is_connected_on_linkedin=req.contact.is_connected_on_linkedin,
        has_inmail_credits=req.contact.has_inmail_credits,
        research_signals=req.research_signals,
        max_touches=req.max_touches,
        max_days=req.max_days,
        preferred_first_channel=req.preferred_first_channel,
        sequence_options=req.sequence_options,
        stage_instructions=req.stage_instructions,
        personality_config=req.personality_config,
        user_feedback=req.user_feedback,
    )

    graph_app, memory = get_graph_app()
    thread_id = f"api_thread_{uuid.uuid4().hex[:12]}"
    config = {"configurable": {"thread_id": thread_id}}

    try:
        result = graph_app.invoke(initial_state.model_dump(), config)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Graph execution failed: {str(e)}")

    final_state = GraphState(**result)
    elapsed = time.time() - start_time

    if not final_state.validated_sequence:
        return GenerateSequenceResponse(
            status="failed",
            lead_id=lead_id,
            campaign_id=req.campaign_id,
            use_native_language=req.use_native_language,
            approval_mode=req.approval_mode,
            total_steps=0,
            steps=[],
            errors=final_state.validation_errors or ["No sequence produced"],
            generation_time_seconds=round(elapsed, 2),
        )

    seq = final_state.validated_sequence
    tz_offset = seq.detected_timezone or 0
    tz_name = seq.detected_timezone_name or "UTC"
    local_tz = timezone(timedelta(hours=tz_offset))

    step_results: List[StepResult] = []
    for step in seq.steps:
        local_dt = step.scheduled_timestamp.astimezone(local_tz)

        msg_result = None
        for mr in final_state.message_generation_results:
            if mr.get("step_number") == step.step_number:
                msg_result = mr
                break

        step_results.append(StepResult(
            step_number=step.step_number,
            action_type=step.action_type.value,
            channel=step.channel,
            scheduled_timestamp_utc=step.scheduled_timestamp.strftime("%Y-%m-%d %H:%M UTC"),
            scheduled_timestamp_local=local_dt.strftime("%Y-%m-%d %H:%M"),
            local_timezone=tz_name,
            wait_delay_seconds=step.wait_delay_seconds,
            wait_delay_human=_format_wait_delay(step.wait_delay_seconds),
            message_language=step.message_language,
            timing_justification=step.timing_justification,
            rationale=step.sequence_architecture_rationale,
            message=msg_result.get("message") if msg_result else None,
            subject=msg_result.get("subject") if msg_result else None,
            message_score=msg_result.get("score") if msg_result else None,
            message_error=msg_result.get("error") if msg_result else None,
        ))

    msg_success = sum(1 for r in final_state.message_generation_results if r.get("success"))
    msg_total = len(final_state.message_generation_results)
    tz_display = f"UTC{tz_offset:+d} ({tz_name})"

    response = GenerateSequenceResponse(
        status="awaiting_approval",
        thread_id=thread_id,
        lead_id=lead_id,
        campaign_id=req.campaign_id,
        detected_language=seq.detected_language,
        detected_language_name=final_state.detected_language_name,
        detected_timezone=tz_display,
        use_native_language=req.use_native_language,
        approval_mode=seq.approval_mode,
        total_steps=len(seq.steps),
        steps=step_results,
        sandbox_adjustments=final_state.sandbox_adjustments,
        message_generation_summary={
            "success": msg_success,
            "total": msg_total,
            "failed": msg_total - msg_success,
        },
        generation_time_seconds=round(elapsed, 2),
        errors=final_state.validation_errors or [],
    )

    # Cache the response for idempotency
    _cache_response(idempotency_key, response.model_dump())

    return response


@app.get("/health")
async def health():
    return {"status": "ok", "service": "sequence-generator"}


@app.post("/api/approve/{thread_id}")
async def approve_and_dispatch_sequence(thread_id: str, req: ApproveSequenceRequest):
    """
    Resume a paused sequence after human approval.
    The graph pauses at 'dispatch_to_temporal' — this endpoint resumes it.

    If approved: dispatches to Temporal.
    If rejected with feedback: regenerates sequence with user feedback injected.
    """
    from sequence_generator.graph.builder import approve_and_dispatch

    graph_app, memory = get_graph_app()
    result = approve_and_dispatch(thread_id, graph_app, memory, req.approved, req.user_feedback)
    return result


# ── Memory Management (proxies to message generator) ──────────────

@app.get("/api/memory/status")
async def memory_status():
    """
    Check memory status on the message generator.
    Proxies to message generator's /api/memory/status.
    """
    import httpx
    rest_url = os.getenv("MCP_REST_URL", "http://localhost:8000").rstrip("/")
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            resp = await client.get(f"{rest_url}/api/memory/status")
            return resp.json()
    except Exception as e:
        return {"error": f"Message generator unreachable: {str(e)}"}


@app.post("/api/memory/flush")
async def memory_flush():
    """
    Wipe all memory on the message generator AND reset this server's
    LangGraph checkpointer (MemorySaver) so sequences start fresh.
    """
    import httpx
    global _graph_app

    # 1. Flush message generator memory
    msg_gen_result = {"error": "Message generator unreachable"}
    rest_url = os.getenv("MESSAGE_GENERATOR_URL", "http://localhost:8000").rstrip("/")
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            resp = await client.post(f"{rest_url}/api/memory/flush")
            msg_gen_result = resp.json()
    except Exception:
        pass

    # 2. Reset graph app AND memory (fresh MemorySaver on next request)
    global _graph_memory
    with _graph_app_lock:
        _graph_app = None
        _graph_memory = None

    return {
        "success": True,
        "message_generator_flush": msg_gen_result,
        "graph_checkpointer": "reset (fresh MemorySaver on next request)",
    }


# ── Observability (for Outreach Orchestrator / Global Orchestrator) ──────

@app.get("/api/observability")
async def get_observability():
    """
    Aggregated observability metrics from the Sequence Generator.
    Returns token usage, Gemini call counts, model info, uptime.
    """
    obs_summary = seq_prompt_store.get_summary()
    return {
        "module": "sequence_generator",
        "total_tokens": obs_summary.get("total_tokens", 0),
        "total_tokens_in": obs_summary.get("total_tokens_in", 0),
        "total_tokens_out": obs_summary.get("total_tokens_out", 0),
        "total_gemini_calls": obs_summary.get("total_calls", 0),
        "calls_by_agent": obs_summary.get("calls_by_agent", {}),
        "success_rate": obs_summary.get("success_rate", 0.0),
        "avg_latency_ms": obs_summary.get("avg_latency_ms", 0.0),
        "model": seq_runtime_config.get("GEMINI_MODEL", os.getenv("GEMINI_MODEL", "gemini-3.1-flash-lite-preview")),
        "fallback_model": os.getenv("GEMINI_FALLBACK_MODEL", "models/gemma-3-27b-it"),
        "max_retries": int(seq_runtime_config.get("MAX_RETRIES", os.getenv("MAX_RETRIES", "3"))),
        "pending_feedback_count": sum(len(v) for v in seq_pending_feedback.values()),
        "config_overrides": seq_runtime_config.get_all_overrides(),
    }


@app.get("/api/observability/prompts")
async def get_prompt_history(limit: int = 50, agent_step: Optional[str] = None):
    """
    Returns prompt history from Gemini calls.
    """
    return seq_prompt_store.get_history(limit=limit, agent_step=agent_step)


class SeqConfigOverrideRequest(BaseModel):
    overrides: Dict[str, Any]


@app.post("/api/config/override")
async def override_config(req: SeqConfigOverrideRequest):
    """
    Override runtime settings (MAX_RETRIES, GEMINI_MODEL, GEMINI_TEMPERATURE, etc.).
    Only whitelisted keys are accepted.
    """
    accepted = {}
    rejected = {}
    for key, value in req.overrides.items():
        if seq_runtime_config.set(key, value):
            accepted[key] = value
        else:
            rejected[key] = "not in allowed override keys"
    return {
        "success": len(rejected) == 0,
        "accepted": accepted,
        "rejected": rejected,
        "current_overrides": seq_runtime_config.get_all_overrides(),
    }


@app.post("/api/config/reset")
async def reset_config():
    """Reset all runtime config overrides to defaults."""
    seq_runtime_config.reset()
    return {"success": True, "message": "All overrides cleared"}


class SeqFeedbackRequest(BaseModel):
    feedback: str
    lead_id: Optional[str] = None


@app.post("/api/feedback")
async def inject_feedback(req: SeqFeedbackRequest):
    """
    Inject feedback from the global orchestrator.
    The feedback is prepended to the next Gemini prompt as a system directive.

    If lead_id is provided, the feedback is scoped to that lead only —
    it will NOT be consumed by any other concurrent sequence.
    If lead_id is omitted, the feedback goes to a shared bucket available
    to any lead (backward-compatible, but subject to race conditions under
    concurrency).
    """
    key = req.lead_id or "__shared__"
    seq_pending_feedback.setdefault(key, []).append(req.feedback)
    return {
        "success": True,
        "pending_feedback_count": sum(len(v) for v in seq_pending_feedback.values()),
        "scoped_to_lead_id": req.lead_id,
        "message": "Feedback will be prepended to next Gemini prompt for this lead",
    }


@app.get("/api/paused-threads")
async def get_paused_threads():
    """
    List threads currently paused at the dispatch_to_temporal interrupt.

    The graph is compiled with interrupt_before=['dispatch_to_temporal'],
    so any thread that has completed sequence generation but not yet been
    approved/rejected will be paused here.

    Uses graph.get_state() which returns a StateSnapshot with a .next tuple
    containing the names of nodes scheduled to run next.  A thread paused at
    the interrupt will have 'dispatch_to_temporal' in .next.

    Returns a list of paused thread IDs with available context (company,
    contact info) extracted from the checkpoint state.
    """
    graph_app, memory = get_graph_app()
    if memory is None or graph_app is None:
        return {"paused_threads": []}

    paused_threads = []
    # memory.storage is a defaultdict keyed by thread_id
    for thread_id in list(memory.storage.keys()):
        try:
            config = {"configurable": {"thread_id": thread_id}}
            state = graph_app.get_state(config)
            # state.next is a tuple of node names scheduled to run next
            if state and "dispatch_to_temporal" in state.next:
                values = state.values if isinstance(state.values, dict) else {}
                contact_info = values.get("contact_info", {})
                paused_threads.append({
                    "thread_id": thread_id,
                    "paused_at": "dispatch_to_temporal",
                    "entreprise": values.get("entreprise", ""),
                    "lead_id": values.get("lead_id", ""),
                    "contact_info": {
                        "full_name": contact_info.get("full_name", "") if isinstance(contact_info, dict) else "",
                        "email": contact_info.get("email", "") if isinstance(contact_info, dict) else "",
                        "country": contact_info.get("country", "") if isinstance(contact_info, dict) else "",
                    },
                })
        except Exception:
            # Skip threads whose state can't be read
            continue

    return {"paused_threads": paused_threads}


@app.post("/api/observability/clear")
async def clear_prompt_history():
    """Clear prompt history."""
    count = seq_prompt_store.clear()
    return {"success": True, "cleared": count}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8001)
