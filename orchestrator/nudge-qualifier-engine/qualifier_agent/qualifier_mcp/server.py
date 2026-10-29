"""
mcp/server.py
─────────────
FastMCP server for the Strategic Qualifier pipeline.

Exposes 6 tools to the orchestrator:
  1. start_campaign          — Phase 1: ICP extraction, pauses for company sourcing
  2. resume_with_companies   — Phase 2: Nodes 2-4 (firmographic rank), pauses for human review
  2b. rescore_with_intent    — Update ranked companies with sourcer intent signals
  3. resume_with_approvals   — Phase 3: Node 5, completes pipeline
  4. get_campaign_status     — Read current campaign state from DB
  5. get_pending_campaigns   — Read all campaigns awaiting approval for a user

Each tool:
  - Validates input via Pydantic (FastMCP does this automatically)
  - Calls the real pipeline or CampaignStatusManager
  - Returns a structured output dict
  - Handles its own errors and writes to DB on failure
  - Never leaks internal LangGraph state to the orchestrator
"""

from __future__ import annotations

import logging
import uuid
from typing import Any, Dict, List, Optional

from fastmcp import FastMCP
from langgraph.errors import GraphInterrupt
from langgraph.types import Command

from graph.campaign_status import CampaignStatusManager, CampaignStatus
from graph.campaign_data import CampaignDataManager
from graph.workflow import get_pipeline
from utils.usage_tracker import (
    get_campaign_accumulator,
    get_usage_summary,
    clear_campaign_accumulator,
    make_callback,
)
from qualifier_mcp.schemas import (
    StartCampaignInput,
    StartCampaignOutput,
    ResumeWithCompaniesInput,
    ResumeWithCompaniesOutput,
    RescoreWithIntentInput,
    RescoreWithIntentOutput,
    ResumeWithApprovalsInput,
    ResumeWithApprovalsOutput,
    GetCampaignStatusInput,
    GetCampaignStatusOutput,
    GetPendingCampaignsInput,
    GetPendingCampaignsOutput,
    ICPFilters,
    CompanySizeFilter,
    RevenueRangeFilter,
    RankedCompany,
    RankedPersona,
    PendingCampaign,
)
from brain.scoring import evaluate_company_intent, intent_breakdown_from_analysis
from brain.config import safe_load_firmographic_weights
from langchain_groq import ChatGroq
import os

logger = logging.getLogger(__name__)

mcp = FastMCP("strategic-qualifier")

_manager = CampaignStatusManager()
_data_manager = CampaignDataManager()


# ── Helpers ───────────────────────────────────────────────────────────────────

def _pop_tool_usage(campaign_id: str) -> Dict[str, Any]:
    """
    Snapshot Groq usage for this MCP process invocation, then clear the
    in-memory accumulator (keep_alive=False → process dies after the call).
    """
    accumulator = get_campaign_accumulator(campaign_id)
    summary = get_usage_summary(accumulator)
    clear_campaign_accumulator(campaign_id)
    return summary


def _pop_and_record_tool_usage(campaign_id: str, tool_name: str) -> Dict[str, Any]:
    """
    Pop the in-memory token usage accumulator for this tool invocation, and
    persist it into the Postgres `token_usage` table.
    """
    usage = _pop_tool_usage(campaign_id)
    try:
        _data_manager.insert_token_usage(
            campaign_id=campaign_id,
            tool_name=tool_name,
            usage=usage,
        )
    except Exception as exc:
        # Never break the pipeline response due to observability storage issues.
        logger.exception(
            "Failed to persist token usage (tool=%s campaign_id=%s): %s",
            tool_name,
            campaign_id,
            exc,
        )
    return usage


def _extract_interrupt_payload(snapshot) -> Optional[Any]:
    """
    Extract the interrupt payload from a LangGraph state snapshot.
    Returns None if no interrupt is present (pipeline ran to completion
    or failed before reaching an interrupt point).

    Payload shapes:
      - company_sourcing: dict with type/icp_filters
      - human_review: list of ranked company review dicts
    """
    if not snapshot.tasks:
        return None
    for task in snapshot.tasks:
        if hasattr(task, "interrupts") and task.interrupts:
            return task.interrupts[0].value
    return None


def _run_until_interrupt(pipeline, stream_input: Any, config: Dict[str, Any]) -> None:
    """
    Stream the graph until the next interrupt.

    Only GraphInterrupt is expected/benign. Any other exception must propagate
    so callers can mark the campaign failed instead of returning empty ranks.
    """
    try:
        for _ in pipeline.stream(stream_input, config, stream_mode="values"):
            pass
    except GraphInterrupt:
        logger.info("pipeline paused at interrupt (expected)")


def _build_icp_filters(interrupt_payload: Dict[str, Any]) -> ICPFilters:
    """Build a typed ICPFilters object from the Node 1.5 interrupt payload."""
    filters = interrupt_payload.get("icp_filters", {})
    size    = filters.get("company_size", {}) or {}
    revenue = filters.get("revenue_range", {}) or {}
    return ICPFilters(
        industries        = filters.get("industries", []),
        target_countries  = filters.get("target_countries", []),
        target_continents = filters.get("target_continents", []),
        company_size      = CompanySizeFilter(
            min=size.get("min"),
            max=size.get("max"),
        ),
        target_roles      = filters.get("target_roles") or [],
        revenue_range     = RevenueRangeFilter(
            min=revenue.get("min"),
            max=revenue.get("max"),
        ),
        tech_stack        = filters.get("tech_stack") or [],
        growth_stage      = filters.get("growth_stage"),
        funding_stage     = filters.get("funding_stage"),
        target_cities     = filters.get("target_cities") or [],
    )


def _build_ranked_companies(companies: List[Dict[str, Any]]) -> List[RankedCompany]:
    """Convert raw company dicts from state into typed RankedCompany objects."""
    return [
        RankedCompany(
            apollo_id             = co.get("apollo_id"),
            name                  = co.get("name", "Unknown"),
            domain                = co.get("domain"),
            qualification_metrics = co.get("qualification_metrics"),
            is_subsidiary         = co.get("is_subsidiary", False),
            parent_company        = co.get("parent_company"),
        )
        for co in companies
    ]


def _build_ranked_personas(personas: List[Dict[str, Any]]) -> List[RankedPersona]:
    """Convert raw persona dicts from state into typed RankedPersona objects."""
    return [
        RankedPersona(
            apollo_id             = p.get("apollo_id"),
            name                  = p.get("name"),
            title                 = p.get("title"),
            seniority             = p.get("seniority"),
            email                 = p.get("email"),
            phone_number          = p.get("phone_number") or p.get("phone"),
            persona_score         = p.get("persona_score"),
            is_linkedin_connected = p.get("is_linkedin_connected"),
            intent                = p.get("intent") or None,
            public_signals        = p.get("public_signals") or p.get("intent"),
            metrics               = p.get("metrics"),
        )
        for p in personas
    ]


# ══════════════════════════════════════════════════════════════════════════════
# TOOL 1 — start_campaign
# ══════════════════════════════════════════════════════════════════════════════

@mcp.tool()
def start_campaign(
    user_id:              str,
    icp_description_text: str,
    user_offering:        str,
    blacklist:            Optional[Dict[str, List[str]]] = None,
    configurable_weights: Optional[Dict[str, float]]    = None,
) -> Dict[str, Any]:
    """
    Start a new qualification campaign.

    Runs Node 1 (ICP extraction) and pauses at Node 1.5 (company sourcing).
    Returns the campaign_id and structured ICP filters for the sourcer agent.

    After calling this tool:
      1. Send icp_filters to your sourcer agent to query Apollo
      2. Call resume_with_companies with the returned raw companies

    Args:
        user_id:              Identifier of the user running this campaign.
        icp_description_text: Natural-language ICP brief (industries, size, location, etc.)
        user_offering:        Description of the product/service being sold.
        blacklist:            Optional companies (regex names) / personas (LinkedIn URLs) to exclude.
        configurable_weights: Optional scoring weight overrides.

    Returns:
        StartCampaignOutput with campaign_id, status, and icp_filters.
    """
    campaign_id = str(uuid.uuid4())
    config      = {"configurable": {"thread_id": campaign_id}}

    blacklist            = blacklist or {"companies": [], "personas": []}
    configurable_weights = configurable_weights or {}

    logger.info("start_campaign: campaign_id=%s user_id=%s", campaign_id, user_id)

    # Create campaign row in DB before touching the pipeline
    _manager.create(
        campaign_id     = campaign_id,
        user_id         = user_id,
        icp_description = icp_description_text,
    )

    # Persist user inputs, blacklist, and weight snapshot (if DB writes fail,
    # we do not block the pipeline execution).
    try:
        _data_manager.upsert_campaign_weights(
            campaign_id=campaign_id,
            weights=configurable_weights,
        )
        _data_manager.upsert_blacklist_entries(
            campaign_id=campaign_id,
            blacklist=blacklist,
        )
    except Exception as exc:
        logger.exception(
            "start_campaign: failed to persist weights/blacklist campaign_id=%s: %s",
            campaign_id,
            exc,
        )

    initial_state = {
        "icp_description_text":        icp_description_text,
        "user_offering":               user_offering,
        "campaign_id":                 campaign_id,
        "sourced_companies":           [],   # empty — sourcer fills this after Phase 1
        "sourced_personas":            [],
        "sourced_personas_by_company": None,
        "blacklist":                   blacklist,
        "configurable_weights":        configurable_weights,
        "user_approved_companies":     None,
        "pipeline_error":              None,
    }

    try:
        with get_pipeline() as pipeline:
            try:
                _run_until_interrupt(pipeline, initial_state, config)
            except Exception as exc:
                _manager.set_failed(campaign_id, str(exc))
                logger.error("start_campaign: stream failed error=%s", exc, exc_info=True)
                return StartCampaignOutput(
                    campaign_id = campaign_id,
                    status      = CampaignStatus.FAILED,
                    icp_filters = ICPFilters(
                        industries=[], target_countries=[],
                        target_continents=[],
                        company_size=CompanySizeFilter(),
                        target_roles=[],
                    ),
                    error = str(exc),
                    usage = _pop_and_record_tool_usage(
                        campaign_id, "start_campaign"
                    ),
                ).model_dump()

            snapshot       = pipeline.get_state(config)
            current        = snapshot.values
            pipeline_error = current.get("pipeline_error")

            if pipeline_error:
                _manager.set_failed(campaign_id, pipeline_error)
                logger.error("start_campaign: pipeline_error=%s", pipeline_error)
                return StartCampaignOutput(
                    campaign_id = campaign_id,
                    status      = CampaignStatus.FAILED,
                    icp_filters = ICPFilters(
                        industries=[], target_countries=[],
                        target_continents=[],
                        company_size=CompanySizeFilter(),
                        target_roles=[],
                    ),
                    error = pipeline_error,
                    usage = _pop_and_record_tool_usage(
                        campaign_id, "start_campaign"
                    ),
                ).model_dump()

            interrupt_payload = _extract_interrupt_payload(snapshot)
            if not isinstance(interrupt_payload, dict):
                error_msg = "Pipeline did not pause at company_sourcing_node — unexpected completion."
                _manager.set_failed(campaign_id, error_msg)
                logger.error("start_campaign: %s", error_msg)
                return StartCampaignOutput(
                    campaign_id = campaign_id,
                    status      = CampaignStatus.FAILED,
                    icp_filters = ICPFilters(
                        industries=[], target_countries=[],
                        target_continents=[],
                        company_size=CompanySizeFilter(),
                        target_roles=[],
                    ),
                    error = error_msg,
                    usage = _pop_and_record_tool_usage(
                        campaign_id, "start_campaign"
                    ),
                ).model_dump()

            icp_filters = _build_icp_filters(interrupt_payload)

            # Persist parsed ICP snapshot + hybrid fields for analytics/debugging.
            try:
                extracted_icp = current.get("extracted_icp")
                _data_manager.upsert_campaign_inputs(
                    campaign_id=campaign_id,
                    raw_icp_text=icp_description_text,
                    user_offering=user_offering,
                    extracted_icp=extracted_icp,
                )
            except Exception as exc:
                logger.exception(
                    "start_campaign: failed to persist campaign_inputs campaign_id=%s: %s",
                    campaign_id,
                    exc,
                )

            logger.info(
                "start_campaign: paused at company_sourcing — "
                "industries=%s countries=%s target_roles=%s",
                icp_filters.industries,
                icp_filters.target_countries,
                icp_filters.target_roles,
            )

            usage_summary = _pop_and_record_tool_usage(campaign_id, "start_campaign")
            return StartCampaignOutput(
                campaign_id = campaign_id,
                status      = CampaignStatus.RUNNING,
                icp_filters = icp_filters,
                error       = None,
                usage       = usage_summary,
            ).model_dump()

    except Exception as exc:
        _manager.set_failed(campaign_id, str(exc))
        logger.error("start_campaign: unexpected error=%s", exc, exc_info=True)
        raise


# ══════════════════════════════════════════════════════════════════════════════
# TOOL 2 — resume_with_companies
# ══════════════════════════════════════════════════════════════════════════════

@mcp.tool()
def resume_with_companies(
    campaign_id:       str,
    sourced_companies: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """
    Resume the pipeline after the sourcer agent returns raw companies.

    Runs Nodes 2-4 (normalize, gate, score, rank) and pauses at Node 4.5
    (human review). Returns ranked companies for user approval.

    Call this after:
      1. Receiving icp_filters from start_campaign
      2. Calling your sourcer agent with those filters
      3. Receiving raw Apollo company dicts back from the sourcer

    After calling this tool:
      1. Show ranked_companies to the user in the frontend
      2. User approves/declines companies
      3. Sourcer fetches personas for approved companies
      4. Call resume_with_approvals

    Args:
        campaign_id:       Campaign identifier from start_campaign.
        sourced_companies: Raw Apollo company dicts from the sourcer agent.

    Returns:
        ResumeWithCompaniesOutput with ranked_companies and disqualification summary.
    """
    config = {"configurable": {"thread_id": campaign_id}}
    logger.info(
        "resume_with_companies: campaign_id=%s companies=%d",
        campaign_id, len(sourced_companies),
    )

    # Persist sourced companies for audit/debugging.
    try:
        _data_manager.insert_campaign_companies(
            campaign_id=campaign_id,
            companies=sourced_companies,
        )
    except Exception as exc:
        logger.exception(
            "resume_with_companies: failed to persist campaign_companies campaign_id=%s: %s",
            campaign_id,
            exc,
        )

    try:
        with get_pipeline() as pipeline:
            try:
                _run_until_interrupt(
                    pipeline,
                    Command(resume=sourced_companies),
                    config,
                )
            except Exception as exc:
                _manager.set_failed(campaign_id, str(exc))
                logger.error(
                    "resume_with_companies: stream failed error=%s",
                    exc,
                    exc_info=True,
                )
                return ResumeWithCompaniesOutput(
                    campaign_id              = campaign_id,
                    status                   = CampaignStatus.FAILED,
                    ranked_companies         = [],
                    nurture_companies        = [],
                    disqualification_summary = {},
                    error                    = str(exc),
                    usage                    = _pop_and_record_tool_usage(
                        campaign_id, "resume_with_companies"
                    ),
                ).model_dump()

            snapshot       = pipeline.get_state(config)
            current        = snapshot.values
            pipeline_error = current.get("pipeline_error")

            if pipeline_error:
                _manager.set_failed(campaign_id, pipeline_error)
                logger.error("resume_with_companies: pipeline_error=%s", pipeline_error)
                return ResumeWithCompaniesOutput(
                    campaign_id              = campaign_id,
                    status                   = CampaignStatus.FAILED,
                    ranked_companies         = [],
                    nurture_companies        = [],
                    disqualification_summary = {},
                    error                    = pipeline_error,
                    usage                    = _pop_and_record_tool_usage(
                        campaign_id, "resume_with_companies"
                    ),
                ).model_dump()

            ranked   = list(current.get("ranked_companies") or [])
            nurture  = list(current.get("nurture_companies") or [])
            disq_log = current.get("disqualification_log") or {}
            summary  = disq_log.get("summary", {}) if isinstance(disq_log, dict) else {}

            interrupt_payload = _extract_interrupt_payload(snapshot)
            if (
                isinstance(interrupt_payload, dict)
                and interrupt_payload.get("type") == "company_sourcing_required"
            ):
                error_msg = (
                    "Pipeline still paused at company_sourcing after resume — "
                    "company ranking did not run."
                )
                _manager.set_failed(campaign_id, error_msg)
                logger.error("resume_with_companies: %s", error_msg)
                return ResumeWithCompaniesOutput(
                    campaign_id              = campaign_id,
                    status                   = CampaignStatus.FAILED,
                    ranked_companies         = [],
                    nurture_companies        = [],
                    disqualification_summary = summary if isinstance(summary, dict) else {},
                    error                    = error_msg,
                    usage                    = _pop_and_record_tool_usage(
                        campaign_id, "resume_with_companies"
                    ),
                ).model_dump()

            if interrupt_payload is None:
                error_msg = (
                    "Pipeline did not pause at human_review after company ranking."
                )
                _manager.set_failed(campaign_id, error_msg)
                logger.error("resume_with_companies: %s", error_msg)
                return ResumeWithCompaniesOutput(
                    campaign_id              = campaign_id,
                    status                   = CampaignStatus.FAILED,
                    ranked_companies         = [],
                    nurture_companies        = [],
                    disqualification_summary = summary if isinstance(summary, dict) else {},
                    error                    = error_msg,
                    usage                    = _pop_and_record_tool_usage(
                        campaign_id, "resume_with_companies"
                    ),
                ).model_dump()

            # Fallback: human_review interrupt payload carries the review list
            # when values.ranked_companies is unexpectedly empty after pause.
            if not ranked and isinstance(interrupt_payload, list):
                ranked = [c for c in interrupt_payload if isinstance(c, dict)]
                logger.warning(
                    "resume_with_companies: ranked_companies empty in state — "
                    "recovered %d from interrupt payload",
                    len(ranked),
                )

            # Store ranked companies in DB for frontend UI restoration
            review_payload = [
                {
                    "apollo_id":             co.get("apollo_id"),
                    "name":                  co.get("name"),
                    "domain":                co.get("domain"),
                    "qualification_metrics": co.get("qualification_metrics", {}),
                    "is_subsidiary":         co.get("is_subsidiary", False),
                    "parent_company":        co.get("parent_company"),
                }
                for co in ranked
            ]
            _manager.set_ready_for_personas(campaign_id, review_payload)

            logger.info(
                "resume_with_companies: ranked=%d nurture=%d disqualified=%d",
                len(ranked), len(nurture),
                disq_log.get("total_disqualified", 0) if isinstance(disq_log, dict) else 0,
            )

            return ResumeWithCompaniesOutput(
                campaign_id              = campaign_id,
                status                   = CampaignStatus.READY_FOR_PERSONAS,
                ranked_companies         = _build_ranked_companies(ranked),
                nurture_companies        = _build_ranked_companies(nurture),
                disqualification_summary = summary if isinstance(summary, dict) else {},
                error                    = None,
                usage                    = _pop_and_record_tool_usage(
                    campaign_id, "resume_with_companies"
                ),
            ).model_dump()

    except Exception as exc:
        _manager.set_failed(campaign_id, str(exc))
        logger.error("resume_with_companies: unexpected error=%s", exc, exc_info=True)
        raise


# ══════════════════════════════════════════════════════════════════════════════
# TOOL 2b — rescore_with_intent
# ══════════════════════════════════════════════════════════════════════════════

def _get_rescore_llm() -> ChatGroq:
    return ChatGroq(
        model_name="llama-3.3-70b-versatile",
        temperature=0.0,
        groq_api_key=os.getenv("GROQ_API_KEY"),
    )


@mcp.tool()
def rescore_with_intent(
    campaign_id: str,
    intent_by_apollo_id: Dict[str, Dict[str, Any]],
) -> Dict[str, Any]:
    """
    Update intent scores on ranked companies after the sourcer fetched intent.

    Call this after:
      1. resume_with_companies (firmographic ranking, often with empty intent)
      2. Sourcer fetch_intent for selected/ranked company apollo_ids

    Stays at ready_for_personas so the orchestrator can later call resume_with_approvals.
    """
    config = {"configurable": {"thread_id": campaign_id}}
    logger.info(
        "rescore_with_intent: campaign_id=%s intents=%d",
        campaign_id, len(intent_by_apollo_id or {}),
    )

    try:
        with get_pipeline() as pipeline:
            snapshot = pipeline.get_state(config)
            if not snapshot or not snapshot.values:
                error_msg = f"No pipeline state found for campaign_id={campaign_id}"
                _manager.set_failed(campaign_id, error_msg)
                return RescoreWithIntentOutput(
                    campaign_id=campaign_id,
                    status=CampaignStatus.FAILED,
                    ranked_companies=[],
                    nurture_companies=[],
                    error=error_msg,
                    usage=_pop_and_record_tool_usage(
                        campaign_id, "rescore_with_intent"
                    ),
                ).model_dump()

            current = snapshot.values
            ranked = list(current.get("ranked_companies") or [])
            nurture = list(current.get("nurture_companies") or [])
            icp = current.get("extracted_icp")
            if isinstance(icp, dict):
                try:
                    from brain.schemas import ICPAttributes
                    icp = ICPAttributes.model_validate(icp)
                except Exception:
                    logger.warning("rescore_with_intent: could not rehydrate extracted_icp")
            user_offering = current.get("user_offering", "")
            firm_weights = safe_load_firmographic_weights(current.get("configurable_weights"))
            llm = _get_rescore_llm()
            accumulator = get_campaign_accumulator(campaign_id)
            rescore_cb = make_callback(accumulator, "rescore_with_intent")

            def _rescore_list(companies: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
                updated: List[Dict[str, Any]] = []
                for co in companies:
                    apollo_id = co.get("apollo_id")
                    metrics = dict(co.get("qualification_metrics") or {})
                    firm_score = float(metrics.get("firmographic_score") or 0.0)

                    if apollo_id and apollo_id in intent_by_apollo_id:
                        signals = intent_by_apollo_id[apollo_id] or {}
                        co = dict(co)
                        job_offers = signals.get("job_offers") or []
                        news = signals.get("news") or []
                        company_intent_summary = (signals.get("company_intent_summary") or "").strip()
                        co["intent_signals"] = {
                            "job_offers": job_offers,
                            "news": news,
                            "company_intent_summary": company_intent_summary,
                        }
                        if company_intent_summary:
                            co["company_intent_summary"] = company_intent_summary
                        intent_results = None
                        if firm_score >= firm_weights.passing_threshold:
                            if (
                                not job_offers
                                and not news
                                and not (co.get("funding_events") or [])
                                and not company_intent_summary
                            ):
                                intent_score = 0
                                intent_reasoning = (
                                    "No commercial intent signals found "
                                    "(no recent job offers, news, or funding)."
                                )
                            else:
                                try:
                                    intent_results = evaluate_company_intent(
                                        co, icp, llm,
                                        user_offering=user_offering,
                                        firm_weights=firm_weights,
                                        callbacks=[rescore_cb],
                                        include_funding_as_signal=True,
                                    )
                                    intent_score = intent_results.intent_score
                                    intent_reasoning = intent_results.reasoning
                                except Exception as exc:
                                    logger.error("rescore intent failed for %s: %s", apollo_id, exc)
                                    intent_score = 0
                                    intent_reasoning = f"Intent rescore failed: {exc}"
                        else:
                            intent_score = 0
                            intent_reasoning = (
                                f"Skipped: firmographic fit ({firm_score:.1f}) below "
                                f"passing threshold ({firm_weights.passing_threshold})."
                            )

                        total_score = (
                            (firm_score * firm_weights.firmographic_weight)
                            + (intent_score * firm_weights.intent_weight)
                        )
                        if total_score >= 80.0:
                            tier = "A"
                        elif total_score >= 50.0:
                            tier = "B"
                        else:
                            tier = "C"

                        metrics.update({
                            "intent_score": intent_score,
                            "intent_reasoning": intent_reasoning,
                            "intent_breakdown": (
                                intent_breakdown_from_analysis(intent_results)
                                if intent_results is not None
                                else None
                            ),
                            "total_score": round(total_score, 2),
                            "tier": tier if metrics.get("tier") != "Nurture" else "Nurture",
                        })
                        co["qualification_metrics"] = metrics

                    updated.append(co)
                updated.sort(
                    key=lambda c: (c.get("qualification_metrics") or {}).get("total_score", 0),
                    reverse=True,
                )
                return updated

            ranked = _rescore_list(ranked)
            nurture = _rescore_list(nurture)

            # Also patch sourced_companies intent for downstream persona context
            sourced = list(current.get("sourced_companies") or [])
            for i, co in enumerate(sourced):
                apollo_id = co.get("apollo_id")
                if apollo_id and apollo_id in intent_by_apollo_id:
                    signals = intent_by_apollo_id[apollo_id] or {}
                    sourced[i] = {
                        **co,
                        "intent_signals": {
                            "job_offers": signals.get("job_offers") or [],
                            "news": signals.get("news") or [],
                            "company_intent_summary": (signals.get("company_intent_summary") or "").strip(),
                        },
                    }

            pipeline.update_state(
                config,
                {
                    "ranked_companies": ranked,
                    "nurture_companies": nurture,
                    "sourced_companies": sourced,
                },
            )

            review_payload = [
                {
                    "apollo_id": co.get("apollo_id"),
                    "name": co.get("name"),
                    "domain": co.get("domain"),
                    "qualification_metrics": co.get("qualification_metrics", {}),
                    "is_subsidiary": co.get("is_subsidiary", False),
                    "parent_company": co.get("parent_company"),
                }
                for co in ranked
            ]
            _manager.set_ready_for_personas(campaign_id, review_payload)

            logger.info("rescore_with_intent: updated ranked=%d nurture=%d", len(ranked), len(nurture))
            return RescoreWithIntentOutput(
                campaign_id=campaign_id,
                status=CampaignStatus.READY_FOR_PERSONAS,
                ranked_companies=_build_ranked_companies(ranked),
                nurture_companies=_build_ranked_companies(nurture),
                error=None,
                usage=_pop_and_record_tool_usage(
                    campaign_id, "rescore_with_intent"
                ),
            ).model_dump()

    except Exception as exc:
        _manager.set_failed(campaign_id, str(exc))
        logger.error("rescore_with_intent: unexpected error=%s", exc, exc_info=True)
        raise


# ══════════════════════════════════════════════════════════════════════════════
# TOOL 3 — resume_with_approvals
# ══════════════════════════════════════════════════════════════════════════════

@mcp.tool()
def resume_with_approvals(
    campaign_id:                 str,
    approved_apollo_ids:         List[str],
    sourced_personas_by_company: Dict[str, List[Dict[str, Any]]],
) -> Dict[str, Any]:
    """
    Resume the pipeline after user approves companies and sourcer returns personas.

    Runs Node 5 (persona ranking) for approved companies only.
    Completes the pipeline and returns ranked personas.

    Call this after:
      1. User has approved/declined companies from the frontend
      2. Sourcer has fetched personas for approved companies only
      3. You have sourced_personas_by_company keyed by apollo_id

    Args:
        campaign_id:                 Campaign identifier.
        approved_apollo_ids:         Apollo IDs of companies the user approved.
        sourced_personas_by_company: Personas from sourcer, keyed by apollo_id.

    Returns:
        ResumeWithApprovalsOutput with all ranked personas.
    """
    config = {"configurable": {"thread_id": campaign_id}}
    logger.info(
        "resume_with_approvals: campaign_id=%s approved=%d",
        campaign_id, len(approved_apollo_ids),
    )

    _manager.set_resuming(campaign_id)

    try:
        # Persist sourced personas for audit/debugging.
        try:
            _data_manager.insert_campaign_personas(
                campaign_id=campaign_id,
                sourced_personas_by_company=sourced_personas_by_company,
            )
        except Exception as exc:
            logger.exception(
                "resume_with_approvals: failed to persist campaign_personas campaign_id=%s: %s",
                campaign_id,
                exc,
            )

        with get_pipeline() as pipeline:
            # Inject personas into state before resuming
            pipeline.update_state(
                config,
                {"sourced_personas_by_company": sourced_personas_by_company},
            )

            # If scoring left sourced_companies empty but personas arrived,
            # seed stub companies so rank_personas_node can still score them.
            snapshot = pipeline.get_state(config)
            current = snapshot.values if snapshot else {}
            existing_companies = list((current or {}).get("sourced_companies") or [])
            if not existing_companies and sourced_personas_by_company:
                stubs = []
                ranked_by_id = {
                    c.get("apollo_id"): c
                    for c in (current.get("ranked_companies") or [])
                    if c.get("apollo_id")
                }
                for apollo_id in sourced_personas_by_company.keys():
                    base = ranked_by_id.get(apollo_id) or {"apollo_id": apollo_id}
                    stubs.append(dict(base))
                if stubs:
                    logger.warning(
                        "resume_with_approvals: seeding %d company stubs from personas",
                        len(stubs),
                    )
                    pipeline.update_state(config, {"sourced_companies": stubs})

            try:
                _run_until_interrupt(
                    pipeline,
                    Command(resume=approved_apollo_ids),
                    config,
                )
            except Exception as exc:
                _manager.set_failed(campaign_id, str(exc))
                logger.error(
                    "resume_with_approvals: stream failed error=%s",
                    exc,
                    exc_info=True,
                )
                return ResumeWithApprovalsOutput(
                    campaign_id           = campaign_id,
                    status                = CampaignStatus.FAILED,
                    ranked_personas       = [],
                    total_personas_ranked = 0,
                    error                 = str(exc),
                    usage                 = _pop_and_record_tool_usage(
                        campaign_id, "resume_with_approvals"
                    ),
                ).model_dump()

            snapshot       = pipeline.get_state(config)
            current        = snapshot.values
            pipeline_error = current.get("pipeline_error")

            if pipeline_error:
                _manager.set_failed(campaign_id, pipeline_error)
                logger.error("resume_with_approvals: pipeline_error=%s", pipeline_error)
                return ResumeWithApprovalsOutput(
                    campaign_id          = campaign_id,
                    status               = CampaignStatus.FAILED,
                    ranked_personas      = [],
                    total_personas_ranked = 0,
                    error                = pipeline_error,
                    usage                = _pop_and_record_tool_usage(
                        campaign_id, "resume_with_approvals"
                    ),
                ).model_dump()

            ranked_personas = current.get("ranked_personas", []) or []
            
            # Capture usage summary before marking as completed
            usage_summary = _pop_and_record_tool_usage(
                campaign_id, "resume_with_approvals"
            )
            
            logger.info(
                "resume_with_approvals: usage_summary=%s",
                usage_summary
            )
            
            _manager.set_completed(campaign_id, usage=usage_summary)

            logger.info(
                "resume_with_approvals: completed — personas=%d",
                len(ranked_personas),
            )

            return ResumeWithApprovalsOutput(
                campaign_id           = campaign_id,
                status                = CampaignStatus.COMPLETED,
                ranked_personas       = _build_ranked_personas(ranked_personas),
                total_personas_ranked = len(ranked_personas),
                error                 = None,
                usage                 = usage_summary,
            ).model_dump()

    except Exception as exc:
        _manager.set_failed(campaign_id, str(exc))
        logger.error("resume_with_approvals: unexpected error=%s", exc, exc_info=True)
        raise


# ══════════════════════════════════════════════════════════════════════════════
# TOOL 4 — get_campaign_status
# ══════════════════════════════════════════════════════════════════════════════

@mcp.tool()
def get_campaign_status(campaign_id: str) -> Dict[str, Any]:
    """
    Get the current status and data for a single campaign.

    Use this to:
      - Poll campaign progress while Phase 1 or Phase 2 is running
      - Check if a campaign failed and why
      - Retrieve ranked_companies for a campaign in 'ready_for_personas' state

    Args:
        campaign_id: Campaign identifier returned by start_campaign.

    Returns:
        GetCampaignStatusOutput with current status and relevant data.
    """
    logger.info("get_campaign_status: campaign_id=%s", campaign_id)

    row = _manager.get(campaign_id)
    if not row:
        return GetCampaignStatusOutput(
            campaign_id   = campaign_id,
            user_id       = "unknown",
            status        = "not_found",
            error_message = f"No campaign found with id '{campaign_id}'",
        ).model_dump()

    ranked_companies = None
    if row.get("ranked_companies"):
        ranked_companies = _build_ranked_companies(row["ranked_companies"])

    return GetCampaignStatusOutput(
        campaign_id      = row["campaign_id"],
        user_id          = row["user_id"],
        status           = row["status"],
        ranked_companies = ranked_companies,
        icp_description  = row.get("icp_description"),
        error_message    = row.get("error_message"),
        created_at       = str(row["created_at"]) if row.get("created_at") else None,
        updated_at       = str(row["updated_at"]) if row.get("updated_at") else None,
    ).model_dump()


# ══════════════════════════════════════════════════════════════════════════════
# TOOL 5 — get_pending_campaigns
# ══════════════════════════════════════════════════════════════════════════════

@mcp.tool()
def get_pending_campaigns(user_id: str) -> Dict[str, Any]:
    """
    Get all campaigns currently awaiting user approval for a given user.

    Call this on app open to check if the user has any campaigns waiting
    for their approval. Returns the ranked_companies payload so the frontend
    can immediately render the approval screen without a second round-trip.

    Args:
        user_id: User identifier to check pending campaigns for.

    Returns:
        GetPendingCampaignsOutput with list of campaigns awaiting approval.
    """
    logger.info("get_pending_campaigns: user_id=%s", user_id)

    rows = _manager.get_pending_for_user(user_id)

    pending = [
        PendingCampaign(
            campaign_id      = row["campaign_id"],
            status           = row["status"],
            ranked_companies = _build_ranked_companies(row.get("ranked_companies") or []),
            icp_description  = row.get("icp_description"),
            created_at       = str(row["created_at"]) if row.get("created_at") else None,
            updated_at       = str(row["updated_at"]) if row.get("updated_at") else None,
        )
        for row in rows
    ]

    return GetPendingCampaignsOutput(
        user_id           = user_id,
        pending_campaigns = pending,
        total_pending     = len(pending),
    ).model_dump()