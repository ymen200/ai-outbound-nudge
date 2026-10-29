from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, BackgroundTasks, HTTPException
from pydantic import BaseModel, Field, model_validator

from app.config import settings
from app.mcp_clients.outreach_client import OutreachClient
from app.pipeline import PhaseAPipeline
from app.pipeline.outreach import start_outreach_for_campaign, _register_outreach_send
from app.store import store

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/campaigns", tags=["campaigns"])


class SaveCampaignParamsRequest(BaseModel):
    user_id: str = Field(..., description="Owner of the campaign parameters")
    icp_description_text: Optional[str] = Field(
        None,
        description="Raw ICP brief (defaults to ICP_DESCRIPTION_TEXT from .env)",
    )
    user_offering: Optional[str] = Field(
        None,
        description="Product / offering (defaults to USER_OFFERING from .env)",
    )
    blacklist: Optional[Dict[str, List[str]]] = None
    configurable_weights: Optional[Dict[str, float]] = None
    company_limit: Optional[int] = Field(
        None, description="Override sourcer company limit"
    )
    run_async: bool = Field(
        True,
        description="If true, return immediately and run Phase A in background",
    )

    # ── Outreach (Phase B) configuration ─────────────────────────────────
    auto_start_outreach: bool = Field(
        default=False,
        description="Automatically start Phase B outreach once a FinalLeadPackage is ready",
    )
    sender_company: Optional[str] = Field(
        None, description="Sender's company name (defaults to env)"
    )
    sender_elevator_pitch: Optional[str] = Field(
        None, description="Sender's elevator pitch (defaults to env / raw ICP)"
    )
    offer_name: Optional[str] = Field(
        None, description="Name of the offer/product (defaults to env)"
    )
    solution_summary: Optional[str] = Field(
        None, description="Brief solution description (defaults to env / user_offering)"
    )
    cta: Optional[str] = Field(None, description="Call-to-action text (defaults to env)")
    approval_mode: Optional[str] = Field(
        None, description="Outreach approval mode: per_sequence | per_step | per_step_and_message"
    )
    use_native_language: Optional[bool] = Field(
        None, description="Generate messages in the prospect's native language"
    )
    message_language: Optional[str] = Field(
        None, description="ISO 639-1 language override, e.g. 'fr'"
    )
    has_inmail_credits: Optional[bool] = Field(
        None, description="Sender has LinkedIn InMail credits"
    )
    debug_mode: Optional[bool] = Field(None, description="Propagate DEBUG_MODE to outreach modules")
    # ── AI Sequence Configuration (forwarded to Sequence Generator) ──
    max_touches: Optional[int] = Field(None, description="Max touches in the sequence (AI decides if omitted)")
    max_days: Optional[int] = Field(None, description="Max days the sequence spans (AI decides if omitted)")
    preferred_first_channel: Optional[str] = Field(None, description="Preferred channel for first touch: email | linkedin_dm | linkedin_inmail")
    sequence_options: Optional[Dict[str, Any]] = Field(None, description="Boolean flags for AI: vary_tone, include_breakup, reference_previous, escalate_urgency, cross_channel")
    stage_instructions: Optional[Dict[str, Any]] = Field(None, description="Per-stage custom instructions: {stage_name: instruction_text}")
    # ── Personality Configuration (forwarded to Message Generator writer prompt) ──
    personality_config: Optional[Dict[str, Any]] = Field(None, description="Message voice/style: base_template, personality_traits, always_include_phrases, never_use_phrases, urgency_level, humor_sarcasm, voice_samples")

    @model_validator(mode="after")
    def _apply_env_defaults(self) -> "SaveCampaignParamsRequest":
        if not (self.icp_description_text or "").strip():
            self.icp_description_text = settings.icp_description_text
        if not (self.user_offering or "").strip():
            self.user_offering = settings.user_offering
        if self.sender_company is None:
            self.sender_company = settings.outreach_default_sender_company
        if self.offer_name is None:
            self.offer_name = settings.outreach_default_offer_name
        if self.sender_elevator_pitch is None:
            self.sender_elevator_pitch = settings.outreach_default_sender_elevator_pitch
        if self.solution_summary is None:
            self.solution_summary = settings.outreach_default_solution_summary
        if self.cta is None:
            self.cta = settings.outreach_default_cta
        if self.approval_mode is None:
            self.approval_mode = settings.outreach_default_approval_mode
        if self.use_native_language is None:
            self.use_native_language = settings.outreach_default_use_native_language
        if self.message_language is None:
            self.message_language = settings.outreach_default_message_language
        if self.has_inmail_credits is None:
            self.has_inmail_credits = settings.outreach_default_has_inmail_credits
        if self.debug_mode is None:
            self.debug_mode = settings.outreach_default_debug_mode
        return self


class SaveCampaignParamsResponse(BaseModel):
    user_id: str
    status: str
    message: str


class RangeFilterPatch(BaseModel):
    min: Optional[float] = None
    max: Optional[float] = None


class BlacklistPatch(BaseModel):
    companies: Optional[List[str]] = None
    personas: Optional[List[str]] = None


class UpdateCampaignParamsRequest(BaseModel):
    """Partial update for an existing user_campaign_inputs row.

    Omit any field you do not want to change. Omitted fields keep their
    current stored values (they are not overwritten with null).
    """

    icp_description_text: Optional[str] = None
    user_offering: Optional[str] = None
    blacklist: Optional[BlacklistPatch] = None
    configurable_weights: Optional[Dict[str, float]] = None
    company_limit: Optional[int] = None
    run_async: Optional[bool] = None
    auto_start_outreach: Optional[bool] = None
    sender_company: Optional[str] = None
    sender_elevator_pitch: Optional[str] = None
    offer_name: Optional[str] = None
    solution_summary: Optional[str] = None
    cta: Optional[str] = None
    approval_mode: Optional[str] = None
    use_native_language: Optional[bool] = None
    message_language: Optional[str] = None
    has_inmail_credits: Optional[bool] = None
    debug_mode: Optional[bool] = None
    max_touches: Optional[int] = None
    max_days: Optional[int] = None
    preferred_first_channel: Optional[str] = None
    sequence_options: Optional[Dict[str, Any]] = None
    stage_instructions: Optional[Dict[str, Any]] = None
    personality_config: Optional[Dict[str, Any]] = None

    # ICP sub-attributes (usually filled by the pipeline; editable here)
    industries: Optional[List[str]] = None
    target_countries: Optional[List[str]] = None
    target_continents: Optional[List[str]] = None
    target_roles: Optional[List[str]] = None
    company_size: Optional[RangeFilterPatch] = None
    revenue_range: Optional[RangeFilterPatch] = None
    tech_stack: Optional[List[str]] = None
    growth_stage: Optional[str] = None
    funding_stage: Optional[str] = None
    target_cities: Optional[List[Any]] = None


class UpdateCampaignParamsResponse(BaseModel):
    user_id: str
    status: str
    message: str
    params: Dict[str, Any]
    updated_at: str


class StartCampaignRequest(BaseModel):
    user_id: str = Field(..., description="User whose saved parameters will run the pipeline")


class StartCampaignResponse(BaseModel):
    campaign_id: str
    status: str
    stage: str
    message: str


def _outreach_config_from_params(params: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "auto_start_outreach": bool(params.get("auto_start_outreach", False)),
        "sender_company": params.get("sender_company"),
        "sender_elevator_pitch": params.get("sender_elevator_pitch"),
        "offer_name": params.get("offer_name"),
        "solution_summary": params.get("solution_summary"),
        "cta": params.get("cta"),
        "approval_mode": params.get("approval_mode"),
        "use_native_language": params.get("use_native_language"),
        "message_language": params.get("message_language"),
        "has_inmail_credits": params.get("has_inmail_credits"),
        "debug_mode": params.get("debug_mode"),
        "max_touches": params.get("max_touches"),
        "max_days": params.get("max_days"),
        "preferred_first_channel": params.get("preferred_first_channel"),
        "sequence_options": params.get("sequence_options"),
        "stage_instructions": params.get("stage_instructions"),
        "personality_config": params.get("personality_config"),
    }


def _load_params_for_user(user_id: str) -> Dict[str, Any]:
    record = store.get_user_campaign_params(user_id)
    if not record:
        raise HTTPException(
            status_code=404,
            detail=f"No campaign parameters found for user_id={user_id}. "
            "Call POST /campaigns/params first.",
        )
    return dict(record["params"])


async def _run_phase_a(campaign_id: str, params: Dict[str, Any]) -> None:
    pipeline = PhaseAPipeline()
    try:
        logger.info("Background Phase A starting campaign_id=%s", campaign_id)
        await pipeline.run(
            orchestrator_campaign_id=campaign_id,
            user_id=params["user_id"],
            icp_description_text=params.get("icp_description_text")
            or settings.icp_description_text,
            user_offering=params.get("user_offering") or settings.user_offering,
            blacklist=params.get("blacklist"),
            configurable_weights=params.get("configurable_weights"),
            company_limit=params.get("company_limit"),
            auto_start_outreach=bool(params.get("auto_start_outreach", False)),
        )
        logger.info("Background Phase A finished campaign_id=%s", campaign_id)
    except Exception:
        logger.exception("Background Phase A failed for %s", campaign_id)


@router.post("/params", response_model=SaveCampaignParamsResponse)
async def save_campaign_params(
    body: SaveCampaignParamsRequest,
) -> SaveCampaignParamsResponse:
    """Save campaign draft for a user without starting the pipeline.

    Writes:
    - ``user_campaign_inputs`` (columns + ``params_json`` + raw ICP + empty ICP attrs)
    - ``blacklist_entries`` (one row per company/persona)
    - ``campaign_weights`` (one column per weight)

    ICP sub-attributes (industries, roles, size, …) are filled later by the pipeline.
    """
    params = body.model_dump()
    store.save_campaign_params(user_id=body.user_id, params=params)
    logger.info("POST /campaigns/params user=%s saved (draft tables)", body.user_id)
    return SaveCampaignParamsResponse(
        user_id=body.user_id,
        status="saved",
        message=(
            "Campaign parameters saved. No campaign was started. "
            "Call POST /campaigns/start with this user_id to run."
        ),
    )


@router.get("/params/{user_id}")
async def get_campaign_params(user_id: str) -> Dict[str, Any]:
    """Return saved draft campaign inputs for a user (no pipeline run)."""
    record = store.get_user_campaign_inputs(user_id)
    if not record:
        raise HTTPException(
            status_code=404,
            detail=f"No campaign parameters found for user_id={user_id}",
        )
    return {
        "user_id": record["user_id"],
        "params": record["params"],
        "created_at": record["created_at"],
        "updated_at": record["updated_at"],
    }


@router.patch("/params/{user_id}", response_model=UpdateCampaignParamsResponse)
async def update_campaign_params(
    user_id: str,
    body: UpdateCampaignParamsRequest,
) -> UpdateCampaignParamsResponse:
    """Partially update saved campaign inputs for a user.

    Only fields present in the request body are changed. Omitted fields keep
    their existing values (not overwritten with null). Nested objects
    (``company_size``, ``revenue_range``, ``configurable_weights``,
    ``blacklist``) are merged key-by-key.
    """
    patch = body.model_dump(exclude_unset=True)
    # Nested models: only keep keys the client actually sent.
    if "company_size" in patch and body.company_size is not None:
        patch["company_size"] = body.company_size.model_dump(exclude_unset=True)
    if "revenue_range" in patch and body.revenue_range is not None:
        patch["revenue_range"] = body.revenue_range.model_dump(exclude_unset=True)
    if "blacklist" in patch and body.blacklist is not None:
        patch["blacklist"] = body.blacklist.model_dump(exclude_unset=True)

    if not patch:
        raise HTTPException(
            status_code=400,
            detail="No fields to update. Send at least one attribute to change.",
        )

    record = store.patch_user_campaign_inputs(user_id, patch)
    if not record:
        raise HTTPException(
            status_code=404,
            detail=f"No campaign parameters found for user_id={user_id}. "
            "Call POST /campaigns/params first.",
        )
    logger.info(
        "PATCH /campaigns/params/%s updated keys=%s",
        user_id,
        sorted(patch.keys()),
    )
    return UpdateCampaignParamsResponse(
        user_id=user_id,
        status="updated",
        message="Campaign parameters patched. Unspecified fields were left unchanged.",
        params=record["params"],
        updated_at=record["updated_at"],
    )


@router.post("/start", response_model=StartCampaignResponse)
async def start_campaign(
    body: StartCampaignRequest,
    background_tasks: BackgroundTasks,
) -> StartCampaignResponse:
    """Load saved parameters by user_id and run the Phase A pipeline."""
    params = _load_params_for_user(body.user_id)
    icp = params.get("icp_description_text") or settings.icp_description_text
    offering = params.get("user_offering") or settings.user_offering
    run_async = bool(params.get("run_async", True))

    logger.info(
        "POST /campaigns/start user=%s async=%s icp_len=%d",
        body.user_id,
        run_async,
        len(icp or ""),
    )
    campaign_id = store.create_campaign(
        user_id=body.user_id,
        raw_icp=icp,
        user_offering=offering,
        outreach_config=_outreach_config_from_params(params),
    )

    if run_async:
        background_tasks.add_task(_run_phase_a, campaign_id, params)
        return StartCampaignResponse(
            campaign_id=campaign_id,
            status="running",
            stage="created",
            message="Phase A started in background. Poll GET /campaigns/{id}.",
        )

    pipeline = PhaseAPipeline()
    result = await pipeline.run(
        orchestrator_campaign_id=campaign_id,
        user_id=body.user_id,
        icp_description_text=icp,
        user_offering=offering,
        blacklist=params.get("blacklist"),
        configurable_weights=params.get("configurable_weights"),
        company_limit=params.get("company_limit"),
        auto_start_outreach=bool(params.get("auto_start_outreach", False)),
    )
    return StartCampaignResponse(
        campaign_id=campaign_id,
        status=result["status"],
        stage=result["stage"],
        message=f"Phase A completed with {result['package_count']} packages.",
    )


# ── Message Generator Memory (hub-and-spoke persistence) ────────────────
# NOTE: these must be ABOVE GET /{campaign_id} or FastAPI's path matcher
# will treat "memory" as a campaign_id and return 404 "Campaign not found".

class MemoryRecord(BaseModel):
    key: str
    value: Dict[str, Any]


class MemoryBatchRequest(BaseModel):
    records: List[MemoryRecord] = Field(..., min_length=1)


@router.get("/memory")
async def list_memory(prefix: Optional[str] = None) -> Dict[str, Any]:
    """List all message generator memory records (prospect, learning, offer).

    Called by the message generator on startup to sync its in-memory cache.
    Optionally filter by key prefix: prefix=prospect: returns only prospects."""
    records = store.list_memory_records(prefix=prefix)
    return {"records": [{"key": r["key"], "value": r["value"]} for r in records], "count": len(records)}


@router.post("/memory/batch")
async def batch_save_memory(body: MemoryBatchRequest) -> Dict[str, Any]:
    """Persist memory records from the message generator.

    Called at the end of the message generation pipeline to forward
    prospect/learning/offer memory updates to the central Postgres DB.
    Uses upsert (ON CONFLICT DO UPDATE) so repeated writes are idempotent."""
    count = store.save_memory_records([r.model_dump() for r in body.records])
    logger.info("POST /memory/batch saved=%d", count)
    return {"saved": count}


@router.post("/memory/flush")
async def flush_memory() -> Dict[str, Any]:
    """Wipe all message generator memory records (debug/testing)."""
    deleted = store.delete_all_memory()
    logger.info("POST /memory/flush deleted=%d", deleted)
    return {"deleted": deleted}


@router.get("/{campaign_id}")
async def get_campaign(campaign_id: str) -> Dict[str, Any]:
    campaign = store.get_campaign(campaign_id)
    if not campaign:
        raise HTTPException(status_code=404, detail="Campaign not found")
    return {
        "campaign": campaign,
        "artifacts": store.list_artifacts(campaign_id),
        "packages": store.list_packages(campaign_id),
        "outreach_threads": store.list_outreach_threads(campaign_id),
        "outreach_steps": store.list_outreach_steps(campaign_id),
        "personas": store.list_campaign_personas(campaign_id),
    }


class DeclineCompaniesRequest(BaseModel):
    company_ids: List[str] = Field(
        ...,
        min_length=1,
        description="campaign_companies.id values returned by GET /campaigns/{id}/companies",
    )


@router.get("/{campaign_id}/companies")
async def list_campaign_companies(campaign_id: str) -> Dict[str, Any]:
    """List sourced companies for a campaign (name + status for review)."""
    campaign = store.get_campaign(campaign_id)
    if not campaign:
        raise HTTPException(status_code=404, detail="Campaign not found")
    companies = store.list_campaign_companies(campaign_id)
    return {
        "campaign_id": campaign_id,
        "count": len(companies),
        "companies": [
            {
                "id": c["id"],
                "company_name": c["company_name"],
                "apollo_company_id": c["apollo_company_id"],
                "status": c.get("status") or "approved",
            }
            for c in companies
        ],
    }


@router.get("/{campaign_id}/personas")
async def list_campaign_personas(campaign_id: str) -> Dict[str, Any]:
    """List sourced personas for a campaign with their scores."""
    campaign = store.get_campaign(campaign_id)
    if not campaign:
        raise HTTPException(status_code=404, detail="Campaign not found")
    personas = store.list_campaign_personas(campaign_id)

    # Build a score lookup from the rank_personas artifact.
    ranked_scores: Dict[str, Dict[str, Any]] = {}
    for artifact in store.list_artifacts(campaign_id):
        if artifact["stage"] == "rank_personas":
            for rp in artifact["payload"].get("ranked_personas") or []:
                aid = rp.get("apollo_id")
                if aid:
                    score = rp.get("persona_score")
                    if score is not None:
                        ranked_scores[str(aid)] = {"persona_score": score}
            break

    return {
        "campaign_id": campaign_id,
        "count": len(personas),
        "personas": [
            {
                "id": p["id"],
                "persona_name": p["persona_name"],
                "apollo_persona_id": p["apollo_persona_id"],
                "apollo_company_id": p["apollo_company_id"],
                "linkedin_url": p["linkedin_url"],
                **ranked_scores.get(p["apollo_persona_id"], {}),
            }
            for p in personas
        ],
    }


@router.post("/{campaign_id}/companies/decline")
async def decline_campaign_companies(
    campaign_id: str,
    body: DeclineCompaniesRequest,
) -> Dict[str, Any]:
    """Mark selected companies as declined (others stay approved)."""
    campaign = store.get_campaign(campaign_id)
    if not campaign:
        raise HTTPException(status_code=404, detail="Campaign not found")

    result = store.decline_campaign_companies(campaign_id, body.company_ids)
    logger.info(
        "POST /campaigns/%s/companies/decline declined=%d already=%d not_found=%d",
        campaign_id,
        len(result["declined"]),
        len(result["already_declined"]),
        len(result["not_found"]),
    )
    return {
        "campaign_id": campaign_id,
        "status": "ok",
        "message": (
            f"Declined {len(result['declined'])} compan"
            f"{'y' if len(result['declined']) == 1 else 'ies'}."
        ),
        **result,
    }


# ── Outreach (Phase B) endpoints ───────────────────────────────────────────

@router.post("/{campaign_id}/outreach")
async def start_outreach(
    campaign_id: str,
    background_tasks: BackgroundTasks,
    lead_ids: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """Start outreach for the selected (or all) lead packages of a campaign."""
    campaign = store.get_campaign(campaign_id)
    if not campaign:
        raise HTTPException(status_code=404, detail="Campaign not found")
    if not store.list_packages(campaign_id):
        raise HTTPException(status_code=404, detail="No lead packages for campaign")

    background_tasks.add_task(start_outreach_for_campaign, campaign_id, lead_ids)
    return {
        "campaign_id": campaign_id,
        "status": "accepted",
        "message": "Outreach started in background",
    }


@router.get("/{campaign_id}/outreach")
async def list_outreach(campaign_id: str) -> Dict[str, Any]:
    """List outreach threads for a campaign."""
    campaign = store.get_campaign(campaign_id)
    if not campaign:
        raise HTTPException(status_code=404, detail="Campaign not found")
    return {
        "campaign_id": campaign_id,
        "threads": store.list_outreach_threads(campaign_id),
    }


class ApproveOutreachRequest(BaseModel):
    approved: bool = True
    feedback: Optional[str] = None


@router.post("/{campaign_id}/outreach/{thread_id}/approve")
async def approve_outreach(
    campaign_id: str,
    thread_id: str,
    req: ApproveOutreachRequest,
) -> Dict[str, Any]:
    """Approve or reject a paused outreach sequence."""
    campaign = store.get_campaign(campaign_id)
    if not campaign:
        raise HTTPException(status_code=404, detail="Campaign not found")

    client = OutreachClient()
    try:
        result = await client.approve_pipeline(
            thread_id=thread_id,
            approved=req.approved,
            feedback=req.feedback,
        )
        # Update all matching thread rows in case of duplicates
        for thread in store.list_outreach_threads(campaign_id):
            if thread.get("thread_id") == thread_id:
                status = "approved" if req.approved else "rejected"
                store.update_outreach_thread_status(
                    thread["id"],
                    status,
                    payload={"approval_result": result},
                )

        # Re-register with Message Generator now that we have the temporal_workflow_id.
        # The initial dispatch registration had an empty workflow_id (awaiting approval).
        twf_id = result.get("temporal_workflow_id")
        if req.approved and twf_id:
            thread_payload = None
            for thread in store.list_outreach_threads(campaign_id):
                if thread.get("thread_id") == thread_id:
                    thread_payload = thread.get("payload", {})
                    break
            if thread_payload:
                req_payload = thread_payload.get("request", {})
                await _register_outreach_send(
                    campaign_id=campaign_id,
                    workflow_id=twf_id,
                    email=req_payload.get("contact_email", ""),
                    linkedin_profile_id=req_payload.get("contact_linkedin_profile_id", ""),
                    linkedin_url=req_payload.get("contact_linkedin", ""),
                    prospect_name=req_payload.get("contact_full_name", ""),
                    prospect_company=req_payload.get("entreprise", ""),
                )

            # ── Persist AI-generated steps to structured DB storage ──
            # After approval the Temporal workflow has generated messages for all
            # steps. Query the workflow state and save each step as a row so the
            # frontend can list steps without hitting Temporal directly.
            try:
                wf_state = await client._raw_request(
                    "GET", f"/api/workflow/{twf_id}/state"
                )
                wf_steps = (wf_state.get("state") or {}).get("steps", [])
                if wf_steps:
                    store.save_outreach_steps(
                        campaign_id=campaign_id,
                        workflow_id=twf_id,
                        thread_id=twf_id,
                        steps=wf_steps,
                    )
                    logger.info(
                        "Persisted %d AI-generated steps for workflow %s",
                        len(wf_steps),
                        twf_id,
                    )
            except Exception:
                # Non-fatal: approval succeeded, just couldn't snapshot steps.
                # The frontend can still query Temporal directly for state.
                logger.warning(
                    "Failed to persist steps for workflow %s",
                    twf_id,
                    exc_info=True,
                )

        return result
    except Exception as exc:
        logger.exception("Failed to approve outreach thread %s", thread_id)
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/{campaign_id}/outreach/observability")
async def get_outreach_observability(campaign_id: str) -> Dict[str, Any]:
    """Relay aggregated observability from the Outreach Orchestrator."""
    campaign = store.get_campaign(campaign_id)
    if not campaign:
        raise HTTPException(status_code=404, detail="Campaign not found")
    client = OutreachClient()
    try:
        return await client.observability()
    except Exception as exc:
        logger.exception("Failed to fetch outreach observability")
        raise HTTPException(status_code=500, detail=str(exc))


# ── DB persistence helper for step-level signal endpoints ──────────

async def _persist_workflow_steps(
    campaign_id: str, workflow_id: str, action: str, client: OutreachClient
) -> None:
    """Query Temporal and refresh the DB snapshot of outreach steps + thread status.

    Called after every signal (approve-step, skip-step, regenerate-step,
    edit-step, update-sequence) so the DB stays in sync with Temporal.

    Updates:
    - ``outreach_sequence_steps`` — full step snapshot (DELETE + INSERT)
    - ``outreach_threads.status`` — derived from workflow state so the
      frontend sees e.g. "in_progress" without querying Temporal directly.

    Reuses the caller's existing OutreachClient instead of spawning a new
    MCP subprocess, since _raw_request is a plain HTTP call."""
    try:
        wf_state = await client._raw_request(
            "GET", f"/api/workflow/{workflow_id}/state"
        )
        state = wf_state.get("state") or {}
        wf_steps = state.get("steps", [])
        if wf_steps:
            store.save_outreach_steps(
                campaign_id=campaign_id,
                workflow_id=workflow_id,
                thread_id=workflow_id,
                steps=wf_steps,
            )
            logger.info(
                "%s: persisted %d steps for workflow %s",
                action, len(wf_steps), workflow_id,
            )

        # ── Derive thread status from workflow state ──────────────────
        wf_status = state.get("status", "")
        thread_status = _thread_status_from_workflow(wf_status, wf_steps)
        for thread in store.list_outreach_threads(campaign_id):
            if thread.get("thread_id") == workflow_id:
                store.update_outreach_thread_status(
                    thread["id"], thread_status,
                )
                break

    except Exception:
        logger.warning(
            "%s: failed to persist steps for workflow %s",
            action, workflow_id, exc_info=True,
        )


def _thread_status_from_workflow(
    wf_status: str, steps: List[Dict[str, Any]]
) -> str:
    """Map Temporal workflow status + step states to a thread status label."""
    steps = steps or []
    if wf_status == "completed":
        return "completed"
    if wf_status == "stopped":
        return "stopped"
    if wf_status == "failed":
        return "failed"
    if wf_status in ("in_progress", "ready"):
        sent = sum(1 for s in steps if s.get("status") == "sent")
        pending = sum(1 for s in steps if s.get("status") in ("pending", "ready"))
        total = len(steps)
        if sent > 0:
            return f"partially_sent ({sent}/{total})"
        if pending > 0:
            return "in_progress"
        return "in_progress"
    return "pending"


# ── Per-step HITL (Temporal workflow signal endpoints) ───────────────

class StepSignalRequest(BaseModel):
    step_num: int
    feedback: Optional[str] = None


class EditStepRequest(BaseModel):
    step_num: int = Field(..., description="Step number to edit")
    message_text: str = Field(..., min_length=1, description="Custom message text from human reviewer")


class CustomSequenceStep(BaseModel):
    step_num: int = Field(..., description="Step number (1-based order)")
    action_type: str = Field("EMAIL_1", description="LINKEDIN_DM, LINKEDIN_INMAIL, LINKEDIN_CONNECT, EMAIL_1")
    channel: str = Field("email", description="linkedin_dm, linkedin_inmail, email")
    wait_delay_seconds: int = Field(0, description="Seconds to wait before sending this step")
    message: str = Field("", description="Message body (human-written when ai_write=False, placeholder when True)")
    ai_write: bool = Field(False, description="Let AI generate the message for this step instead of using the pre-written text")
    subject: Optional[str] = Field(None, description="Email subject line")
    day_offset: int = 0
    time_of_day: str = "10h"
    strategy_notes: str = ""

    @model_validator(mode="after")
    def _require_message_for_text_channels(self):
        # ai_write=True: AI will generate the message, so empty is fine
        if self.ai_write:
            return self
        text_channels = {"EMAIL_1", "LINKEDIN_DM", "LINKEDIN_INMAIL"}
        if self.action_type in text_channels and not self.message.strip():
            raise ValueError(
                f"message is required for {self.action_type} when ai_write=False. "
                "Either provide a message or set ai_write=True to let AI write it."
            )
        return self


class CustomOutreachRequest(BaseModel):
    company_name: str = Field(..., description="Prospect's company name")
    persona: Dict[str, Any] = Field(default_factory=dict, description="Prospect persona info (full_name, job_title, email, linkedin_url, etc.)")
    sender_company: str = Field("My Company", description="Sender's company name")
    use_native_language: bool = Field(False)
    steps: List[CustomSequenceStep] = Field(..., min_length=1, description="Hand-crafted sequence steps with pre-written messages")


@router.get("/{campaign_id}/outreach/workflow/{workflow_id}/state")
async def get_workflow_state(campaign_id: str, workflow_id: str):
    """Query Temporal workflow state via Outreach Orchestrator."""
    campaign = store.get_campaign(campaign_id)
    if not campaign:
        raise HTTPException(status_code=404, detail="Campaign not found")
    client = OutreachClient()
    try:
        return await client._raw_request("GET", f"/api/workflow/{workflow_id}/state")
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.post("/{campaign_id}/outreach/workflow/{workflow_id}/approve-step")
async def approve_workflow_step(campaign_id: str, workflow_id: str, req: StepSignalRequest):
    """Approve a specific step in a per_step / per_step_and_message workflow."""
    campaign = store.get_campaign(campaign_id)
    if not campaign:
        raise HTTPException(status_code=404, detail="Campaign not found")
    client = OutreachClient()
    try:
        result = await client._raw_request(
            "POST", f"/api/workflow/{workflow_id}/signal/approve-step",
            json={"step_num": req.step_num},
        )
        logger.info(
            "approve-step: campaign=%s workflow=%s step=%d",
            campaign_id, workflow_id, req.step_num,
        )
        await _persist_workflow_steps(campaign_id, workflow_id, "approve-step", client)
        return result
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.post("/{campaign_id}/outreach/workflow/{workflow_id}/skip-step")
async def skip_workflow_step(campaign_id: str, workflow_id: str, req: StepSignalRequest):
    """Skip a specific step."""
    campaign = store.get_campaign(campaign_id)
    if not campaign:
        raise HTTPException(status_code=404, detail="Campaign not found")
    client = OutreachClient()
    try:
        result = await client._raw_request(
            "POST", f"/api/workflow/{workflow_id}/signal/skip-step",
            json={"step_num": req.step_num},
        )
        logger.info(
            "skip-step: campaign=%s workflow=%s step=%d",
            campaign_id, workflow_id, req.step_num,
        )
        await _persist_workflow_steps(campaign_id, workflow_id, "skip-step", client)
        return result
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.post("/{campaign_id}/outreach/workflow/{workflow_id}/signal/prospect-connected")
async def signal_prospect_connected(campaign_id: str, workflow_id: str):
    """Notify that the prospect accepted the LinkedIn connection.

    Switches pending EMAIL_1 steps to LINKEDIN_MESSAGE in the Temporal workflow."""
    campaign = store.get_campaign(campaign_id)
    if not campaign:
        raise HTTPException(status_code=404, detail="Campaign not found")
    client = OutreachClient()
    try:
        return await client._raw_request(
            "POST", f"/api/workflow/{workflow_id}/signal/prospect-connected",
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.post("/{campaign_id}/reply")
async def handle_prospect_reply(campaign_id: str):
    """Handle a prospect reply: stop all active sequences and mark as replied.

    Called when a prospect replies to any outreach message (email or LinkedIn).
    Stops all running Temporal workflows for the campaign and updates the
    campaign status so the user is informed."""
    campaign = store.get_campaign(campaign_id)
    if not campaign:
        raise HTTPException(status_code=404, detail="Campaign not found")

    results = []
    client = OutreachClient()

    for thread in store.list_outreach_threads(campaign_id):
        twf_id = (
            thread.get("payload", {})
            .get("response", {})
            .get("temporal_workflow_id")
        )
        if not twf_id or twf_id.startswith("SIMULATED"):
            continue

        try:
            stop_result = await client._raw_request(
                "POST", f"/api/workflow/{twf_id}/signal/stop",
            )
            results.append({"workflow_id": twf_id, "stopped": True, "result": stop_result})
            store.update_outreach_thread_status(
                thread["id"], "replied",
                payload={"stop_reason": "prospect_replied"},
            )
        except Exception as exc:
            results.append({"workflow_id": twf_id, "stopped": False, "error": str(exc)})

    if results:
        msg = f"Prospect reply handled — {len(results)} active sequences stopped"
    else:
        msg = "Prospect reply recorded — no active sequences found to stop"

    return {
        "success": True,
        "campaign_id": campaign_id,
        "message": msg,
        "workflows_stopped": results,
    }


@router.post("/{campaign_id}/outreach/workflow/{workflow_id}/regenerate-step")
async def regenerate_workflow_step(campaign_id: str, workflow_id: str, req: StepSignalRequest):
    """Regenerate a step's message with optional feedback."""
    campaign = store.get_campaign(campaign_id)
    if not campaign:
        raise HTTPException(status_code=404, detail="Campaign not found")
    client = OutreachClient()
    try:
        result = await client._raw_request(
            "POST", f"/api/workflow/{workflow_id}/signal/regenerate-step",
            json={"step_num": req.step_num, "feedback": req.feedback or ""},
        )
        logger.info(
            "regenerate-step: campaign=%s workflow=%s step=%d feedback_len=%d",
            campaign_id, workflow_id, req.step_num, len(req.feedback or ""),
        )
        await _persist_workflow_steps(campaign_id, workflow_id, "regenerate-step", client)
        return result
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.post("/{campaign_id}/outreach/custom")
async def dispatch_custom_outreach(
    campaign_id: str,
    body: CustomOutreachRequest,
) -> Dict[str, Any]:
    """Dispatch a hand-crafted outreach sequence with pre-written messages.

    Zero AI — the user provides every step's channel, timing, and exact message
    text. The sequence is dispatched directly to Temporal and executes as-is.

    Persona data (full_name, job_title, email, linkedin_url) is auto-populated
    from the campaign's existing lead packages when the user omits these fields.
    Any fields the user explicitly provides take priority.

    Use this when:
    - You know exactly what to say and just want it sent
    - The AI-generated sequence wasn't quite right and you'd rather write your own
    - You have a proven outreach template you want to reuse
    """
    campaign = store.get_campaign(campaign_id)
    if not campaign:
        raise HTTPException(status_code=404, detail="Campaign not found")

    # Auto-populate persona from the campaign's lead packages if the user
    # hasn't provided persona fields. The user's explicitly provided fields
    # always take priority.
    packages = store.list_packages(campaign_id)
    resolved_persona: Dict[str, Any] = dict(body.persona)  # user-provided first
    if packages and not resolved_persona:
        # Merge from the first lead package's persona/company data
        first_pkg = packages[0].get("package", {})
        company = first_pkg.get("company") or {}
        persona = first_pkg.get("persona") or {}
        resolved_persona = {
            "full_name": persona.get("name") or persona.get("full_name") or "",
            "job_title": persona.get("title") or persona.get("job_title") or "",
            "email": persona.get("email") or "",
            "linkedin_url": persona.get("linkedin_url") or "",
            "linkedin_profile_id": persona.get("linkedin_profile_id") or persona.get("linkedin_id") or "",
            "country": company.get("country") or "",
        }
    elif packages:
        # User provided some persona fields — merge campaign data for missing ones
        first_pkg = packages[0].get("package", {})
        company = first_pkg.get("company") or {}
        persona = first_pkg.get("persona") or {}
        defaults = {
            "full_name": persona.get("name") or persona.get("full_name") or "",
            "job_title": persona.get("title") or persona.get("job_title") or "",
            "email": persona.get("email") or "",
            "linkedin_url": persona.get("linkedin_url") or "",
            "linkedin_profile_id": persona.get("linkedin_profile_id") or persona.get("linkedin_id") or "",
            "country": company.get("country") or "",
        }
        for key, value in defaults.items():
            if key not in resolved_persona:
                resolved_persona[key] = value

    payload = {
        "lead_id": "",
        "campaign_id": campaign_id,
        "company_name": body.company_name,
        "persona": resolved_persona,
        "sender_company": body.sender_company,
        "use_native_language": body.use_native_language,
        "steps": [s.model_dump() for s in body.steps],
    }

    client = OutreachClient()
    try:
        result = await client._raw_request("POST", "/api/custom/outreach", json=payload)

        # Save outreach thread + structured steps in store
        twf_id = result.get("workflow_id") or ""
        lead_id = result.get("lead_id") or ""
        store.save_outreach_thread(
            campaign_id=campaign_id,
            lead_id=lead_id,
            thread_id=twf_id,
            status="dispatched",
            payload={"request": payload, "response": result},
        )
        # Persist steps as structured rows for DB-level queries
        store.save_outreach_steps(
            campaign_id=campaign_id,
            workflow_id=twf_id,
            thread_id=twf_id,
            steps=[
                {
                    **s.model_dump(),
                    "status": "pending",
                }
                for s in body.steps
            ],
        )
        return result
    except Exception as exc:
        logger.exception("Custom outreach dispatch failed for campaign %s", campaign_id)
        raise HTTPException(status_code=500, detail=str(exc))


@router.post("/{campaign_id}/outreach/workflow/{workflow_id}/edit-step")
async def edit_workflow_step(campaign_id: str, workflow_id: str, req: EditStepRequest):
    """Replace a step's message with human-written text (bypasses Gemini regeneration).

    The human reviewer writes the exact message they want sent. The workflow
    auto-approves the step so it proceeds directly to send without further
    AI generation. Use this when the AI-generated draft is close but needs a
    specific tweak that's easier to type directly than describe in feedback."""
    campaign = store.get_campaign(campaign_id)
    if not campaign:
        raise HTTPException(status_code=404, detail="Campaign not found")
    client = OutreachClient()
    try:
        result = await client._raw_request(
            "POST", f"/api/workflow/{workflow_id}/signal/edit-step",
            json={"step_num": req.step_num, "message_text": req.message_text},
        )
        logger.info(
            "edit-step: campaign=%s workflow=%s step=%d msg_len=%d",
            campaign_id, workflow_id, req.step_num, len(req.message_text),
        )
        await _persist_workflow_steps(campaign_id, workflow_id, "edit-step", client)
        return result
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


# ── Update Sequence (full freedom to restructure) ────────────────

class UpdateStepSpec(BaseModel):
    """A single step in the modified sequence."""
    step_num: int = Field(..., description="Step number (1-based order)")
    action_type: str = Field("EMAIL_1", description="LINKEDIN_DM, LINKEDIN_INMAIL, LINKEDIN_CONNECT, EMAIL_1")
    channel: str = Field("email", description="linkedin_dm, linkedin_inmail, email")
    wait_delay_seconds: int = Field(0, description="Seconds to wait before sending")
    day_offset: int = 0
    time_of_day: str = "10h"
    strategy_notes: str = ""


class UpdateSequenceRequest(BaseModel):
    """Full replacement of the AI-generated sequence."""
    steps: List[UpdateStepSpec] = Field(..., min_length=1, description="Complete replacement step list")
    approve: bool = Field(False, description="Also approve the sequence (unblocks per_sequence review gate)")


@router.post("/{campaign_id}/outreach/workflow/{workflow_id}/update-sequence")
async def update_workflow_sequence(
    campaign_id: str,
    workflow_id: str,
    req: UpdateSequenceRequest,
) -> Dict[str, Any]:
    """Replace the entire AI-generated sequence with a user-modified step list.

    This gives the user COMPLETE CONTROL over an AI-generated sequence:
    - **Change channels**: switch email → LinkedIn DM per step
    - **Reorder steps**: drag-and-drop to rearrange touches
    - **Add new steps**: insert extra touches in the flow
    - **Remove unwanted steps**: delete steps you don't need
    - **Adjust timing**: change wait_delay_seconds per step

    **Preservation rules (handled by Temporal):**
    - Already-sent or failed steps are immutable — never changed.
    - Existing steps that keep their step_num preserve their AI-generated
      message, status, quality_score, and sent_at — only structure changes.
    - New step_nums get AI-generated messages lazily (just-in-time before send).
    - If the currently paused step is removed, it's auto-approved so the
      workflow unblocks and advances.

    **Approve flag:**
    Set ``approve: true`` to also approve the sequence. This is useful when
    the user modifies the sequence during the initial review gate (per_sequence
    mode) and wants it to start executing immediately after the restructure.

    Supports both AI-generated and custom workflows.
    """
    campaign = store.get_campaign(campaign_id)
    if not campaign:
        raise HTTPException(status_code=404, detail="Campaign not found")
    client = OutreachClient()
    try:
        result = await client._raw_request(
            "POST",
            f"/api/workflow/{workflow_id}/signal/update-sequence",
            json=req.model_dump(),
        )
        logger.info(
            "update-sequence: campaign=%s workflow=%s steps=%d approve=%s",
            campaign_id, workflow_id, len(req.steps), req.approve,
        )
        await _persist_workflow_steps(campaign_id, workflow_id, "update-sequence", client)
        return result
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))
