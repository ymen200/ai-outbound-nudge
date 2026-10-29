"""
mcp/schemas.py
──────────────
Pydantic input/output models for the Strategic Qualifier MCP server.

Every tool exposed by server.py uses these models for:
  - Input validation (FastMCP validates automatically on tool call)
  - Output serialization (returned as dicts to the orchestrator)
  - Documentation (FastMCP generates tool descriptions from docstrings + field descriptions)

Naming convention:
  - *Input  — what the orchestrator sends to the tool
  - *Output — what the tool returns to the orchestrator
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


# ══════════════════════════════════════════════════════════════════════════════
# SHARED TYPES
# ══════════════════════════════════════════════════════════════════════════════

class CompanySizeFilter(BaseModel):
    min: Optional[float] = Field(None, description="Minimum employee headcount.")
    max: Optional[float] = Field(None, description="Maximum employee headcount.")


class RevenueRangeFilter(BaseModel):
    min: Optional[float] = Field(None, description="Minimum annual revenue / ARR.")
    max: Optional[float] = Field(None, description="Maximum annual revenue / ARR.")


class ICPFilters(BaseModel):
    """
    Structured ICP attributes extracted by Node 1.
    Sent to orchestrator after company_sourcing interrupt.
    Orchestrator forwards must-have fields to the sourcer and persists all
    attributes (including nice-to-have) on user_campaign_inputs.
    """
    industries:        List[str]          = Field(..., description="Target industry labels e.g. ['Insurance', 'Fintech']")
    target_countries:  List[str]          = Field(..., description="Target country names e.g. ['France', 'Germany']")
    target_continents: List[str]          = Field(..., description="Target continent names e.g. ['Europe']")
    company_size:      CompanySizeFilter  = Field(..., description="Min/max employee headcount range.")
    target_roles:      List[str]          = Field(
        default_factory=list,
        description="ICP target job titles for Apollo persona search e.g. ['VP of Sales', 'CRO'].",
    )
    # Nice-to-have / hybrid fields (scoring + persistence; sourcer may ignore)
    revenue_range:     RevenueRangeFilter = Field(
        default_factory=RevenueRangeFilter,
        description="Preferred annual revenue / ARR band.",
    )
    tech_stack:        List[str]          = Field(
        default_factory=list,
        description="Preferred technologies e.g. ['Salesforce', 'AWS'].",
    )
    growth_stage:      Optional[str]      = Field(
        None, description="Preferred company maturity e.g. 'growth stage'."
    )
    funding_stage:     Optional[str]      = Field(
        None, description="Preferred latest funding round e.g. 'Series B'."
    )
    target_cities:     List[Any]          = Field(
        default_factory=list,
        description="Preferred cities (strings or {city,country,continent} objects).",
    )


class QualificationMetrics(BaseModel):
    """Scoring breakdown attached to each ranked company."""
    firmographic_score: float             = Field(..., description="Raw firmographic fit score 0-100.")
    intent_score:       float             = Field(..., description="LLM intent analysis score 0-100.")
    total_score:        float             = Field(..., description="Composite score 0-100.")
    tier:               str               = Field(..., description="A / B / C / Nurture")
    intent_reasoning:   str               = Field(..., description="LLM explanation of intent score.")
    breakdown:          Dict[str, Any]    = Field(default_factory=dict, description="Per-feature score breakdown.")
    applied_weights:    Dict[str, float]  = Field(default_factory=dict, description="Normalised weights used.")


class RankedCompany(BaseModel):
    """A single company returned after scoring — sent to frontend for approval."""
    apollo_id:             Optional[str]              = Field(None, description="Apollo unique identifier.")
    name:                  str                        = Field(..., description="Company display name.")
    domain:                Optional[str]              = Field(None, description="Company domain.")
    qualification_metrics: Optional[Dict[str, Any]]   = Field(None, description="Full scoring breakdown.")
    is_subsidiary:         bool                       = Field(False, description="Whether this is a subsidiary.")
    parent_company:        Optional[str]              = Field(None, description="Parent company name if subsidiary.")


class RankedPersona(BaseModel):
    """A single scored persona returned after Node 5."""
    apollo_id:             Optional[str]   = Field(None, description="Apollo persona identifier.")
    name:                  Optional[str]   = Field(None, description="Contact full name.")
    title:                 Optional[str]   = Field(None, description="Job title.")
    seniority:             Optional[str]   = Field(None, description="Seniority level.")
    email:                 Optional[str]   = Field(None, description="Contact email.")
    phone_number:          Optional[str]   = Field(None, description="Contact phone number.")
    persona_score:         Optional[float] = Field(None, description="Final persona fit score.")
    is_linkedin_connected: Optional[bool]  = Field(None, description="Whether connected on LinkedIn.")
    intent:                Optional[str]   = Field(
        None,
        description="Neo4j Persona.intent behavioral summary used for timing/signal scoring.",
    )
    public_signals:        Optional[Any]   = Field(
        None,
        description="Persona intent/public signals (mirrors intent when mapped from Neo4j).",
    )
    metrics:               Optional[Dict[str, Any]] = Field(None, description="Fit/reachability/timing breakdown.")


# ══════════════════════════════════════════════════════════════════════════════
# TOOL 1 — start_campaign
# ══════════════════════════════════════════════════════════════════════════════

class StartCampaignInput(BaseModel):
    """
    Input for starting a new campaign.
    Orchestrator sends this when a user submits a new campaign request.
    """
    user_id: str = Field(
        ...,
        description="Identifier of the user who owns this campaign.",
    )
    icp_description_text: str = Field(
        ...,
        description=(
            "Natural-language campaign brief describing the ideal customer profile. "
            "Node 1 parses this into structured ICPAttributes."
        ),
    )
    user_offering: str = Field(
        ...,
        description=(
            "Description of the product or service being sold. "
            "Used by Node 4's intent analysis to score companies relative to "
            "what is actually being offered."
        ),
    )
    blacklist: Optional[Dict[str, List[str]]] = Field(
        default_factory=lambda: {"companies": [], "personas": []},
        description=(
            "Companies and personas to exclude regardless of ICP fit. "
            "companies: name or regex patterns (case-insensitive). "
            "personas: LinkedIn profile URLs."
        ),
    )
    configurable_weights: Optional[Dict[str, float]] = Field(
        default_factory=dict,
        description=(
            "Optional weight/threshold overrides for the scoring engine. "
            "Unknown keys are silently ignored. "
            "Example: {'passing_threshold': 45.0, 'intent_weight': 0.45}"
        ),
    )


class StartCampaignOutput(BaseModel):
    """
    Returned after Phase 1 (Node 1) completes and pipeline pauses at Node 1.5.
    Orchestrator uses icp_filters to call the sourcer agent.
    """
    campaign_id: str = Field(
        ...,
        description="Unique campaign identifier. Also used as LangGraph thread_id.",
    )
    status: str = Field(
        ...,
        description="Campaign status after Phase 1. Always 'running' on success.",
    )
    icp_filters: ICPFilters = Field(
        ...,
        description=(
            "Structured ICP attributes for the sourcer agent to query Apollo. "
            "Send these to the sourcer to fetch matching raw companies."
        ),
    )
    error: Optional[str] = Field(
        None,
        description="Populated if pipeline_error was set during Node 1. Null on success.",
    )
    usage: Optional[Dict[str, Any]] = Field(
        None,
        description="Groq token usage for this tool invocation (ICP extract).",
    )


# ══════════════════════════════════════════════════════════════════════════════
# TOOL 2 — resume_with_companies
# ══════════════════════════════════════════════════════════════════════════════

class ResumeWithCompaniesInput(BaseModel):
    """
    Input for resuming the pipeline after the sourcer returns companies.
    Orchestrator calls this after receiving raw Apollo companies from the sourcer.
    """
    campaign_id: str = Field(
        ...,
        description="Campaign identifier returned by start_campaign.",
    )
    sourced_companies: List[Dict[str, Any]] = Field(
        ...,
        description=(
            "Raw Apollo company dicts returned by the sourcer agent. "
            "Must match the Apollo raw shape — stringified JSON fields, "
            "intent_signals with job_offers and news, etc."
        ),
    )


class ResumeWithCompaniesOutput(BaseModel):
    """
    Returned after Phase 2 (Nodes 2-4) completes and pipeline pauses at Node 4.5.
    Orchestrator passes ranked_companies to the frontend for user approval.
    """
    campaign_id: str = Field(
        ...,
        description="Campaign identifier.",
    )
    status: str = Field(
        ...,
        description="Campaign status. 'ready_for_personas' on success (auto-approve sync).",
    )
    ranked_companies: List[RankedCompany] = Field(
        ...,
        description=(
            "Scored and ranked companies for the user to approve or decline. "
            "Sorted by total_score descending."
        ),
    )
    nurture_companies: List[RankedCompany] = Field(
        default_factory=list,
        description=(
            "Companies that scored below passing_threshold but above "
            "nurture_threshold. Not shown for approval — stored for future use."
        ),
    )
    disqualification_summary: Dict[str, int] = Field(
        default_factory=dict,
        description=(
            "Count of disqualified companies by reason code. "
            "Example: {'BLACKLIST_MATCH': 1, 'MUST_HAVE_SIZE_MISS': 2}"
        ),
    )
    error: Optional[str] = Field(
        None,
        description="Populated if pipeline_error was set. Null on success.",
    )
    usage: Optional[Dict[str, Any]] = Field(
        None,
        description="Groq token usage for this tool invocation (score/rank).",
    )


# ══════════════════════════════════════════════════════════════════════════════
# TOOL 2b — rescore_with_intent  (orchestrator Phase A)
# ══════════════════════════════════════════════════════════════════════════════

class RescoreWithIntentInput(BaseModel):
    """
    After firmographic ranking (resume_with_companies) and sourcer intent fetch,
    orchestrator calls this to update intent scores without leaving the HITL pause.
    """
    campaign_id: str = Field(..., description="Campaign identifier from start_campaign.")
    intent_by_apollo_id: Dict[str, Dict[str, Any]] = Field(
        ...,
        description=(
            "Map of apollo_id → intent_signals. "
            "Shape: {'apollo_id': {'job_offers': [...], 'news': [...], "
            "'company_intent_summary': '...'}}"
        ),
    )


class RescoreWithIntentOutput(BaseModel):
    """Updated ranked companies after intent rescoring."""
    campaign_id: str = Field(..., description="Campaign identifier.")
    status: str = Field(..., description="Usually still 'ready_for_personas'.")
    ranked_companies: List[RankedCompany] = Field(
        default_factory=list,
        description="Companies re-scored with intent, sorted by total_score desc.",
    )
    nurture_companies: List[RankedCompany] = Field(default_factory=list)
    error: Optional[str] = Field(None, description="Error message if rescoring failed.")
    usage: Optional[Dict[str, Any]] = Field(
        None,
        description="Groq token usage for this tool invocation (intent rescore).",
    )

# ══════════════════════════════════════════════════════════════════════════════
# TOOL 3 — resume_with_approvals
# ══════════════════════════════════════════════════════════════════════════════

class ResumeWithApprovalsInput(BaseModel):
    """
    Input for resuming the pipeline after the user approves companies.
    Orchestrator calls this after:
      1. User selects which companies to approve in the frontend
      2. Sourcer fetches personas for approved companies only
    """
    campaign_id: str = Field(
        ...,
        description="Campaign identifier.",
    )
    approved_apollo_ids: List[str] = Field(
        ...,
        description=(
            "Apollo IDs of companies the user approved. "
            "Empty list means user approved all ranked companies."
        ),
    )
    sourced_personas_by_company: Dict[str, List[Dict[str, Any]]] = Field(
        ...,
        description=(
            "Personas fetched by sourcer for approved companies only. "
            "Keyed by apollo_id. "
            "Shape: {'apollo_id': [persona_dict, ...]}"
        ),
    )


class ResumeWithApprovalsOutput(BaseModel):
    """
    Returned after Phase 3 (Node 5) completes and pipeline finishes.
    Contains the final ranked personas for each approved company.
    """
    campaign_id: str = Field(
        ...,
        description="Campaign identifier.",
    )
    status: str = Field(
        ...,
        description="Campaign status. 'completed' on success, 'failed' on error.",
    )
    ranked_personas: List[RankedPersona] = Field(
        default_factory=list,
        description=(
            "All ranked personas across all approved companies, "
            "sorted by persona_score descending."
        ),
    )
    total_personas_ranked: int = Field(
        ...,
        description="Total number of personas ranked across all approved companies.",
    )
    error: Optional[str] = Field(
        None,
        description="Populated if pipeline_error was set or Node 5 failed. Null on success.",
    )
    usage: Optional[Dict[str, Any]] = Field(
        None,
        description="Groq token usage for this tool invocation (persona rank).",
    )


# ══════════════════════════════════════════════════════════════════════════════
# TOOL 4 — get_campaign_status
# ══════════════════════════════════════════════════════════════════════════════

class GetCampaignStatusInput(BaseModel):
    """Input for fetching a single campaign's current status."""
    campaign_id: str = Field(
        ...,
        description="Campaign identifier to look up.",
    )


class GetCampaignStatusOutput(BaseModel):
    """
    Current state of a campaign.
    Orchestrator polls this while pipeline is running,
    or frontend uses it to check what's happening with a campaign.
    """
    campaign_id:      str              = Field(..., description="Campaign identifier.")
    user_id:          str              = Field(..., description="Owner of this campaign.")
    status:           str              = Field(..., description="running | ready_for_personas | resuming | completed | failed")
    ranked_companies: Optional[List[RankedCompany]] = Field(
        None,
        description="Present only when status='ready_for_personas'. Used for UI restoration.",
    )
    icp_description:  Optional[str]   = Field(None, description="Original ICP brief for display.")
    error_message:    Optional[str]   = Field(None, description="Populated if status='failed'.")
    created_at:       Optional[str]   = Field(None, description="ISO timestamp of campaign creation.")
    updated_at:       Optional[str]   = Field(None, description="ISO timestamp of last status change.")


# ══════════════════════════════════════════════════════════════════════════════
# TOOL 5 — get_pending_campaigns
# ══════════════════════════════════════════════════════════════════════════════

class GetPendingCampaignsInput(BaseModel):
    """
    Input for fetching all campaigns awaiting user approval.
    Called by orchestrator on app open to check if user has anything pending.
    """
    user_id: str = Field(
        ...,
        description="User identifier to check pending campaigns for.",
    )


class PendingCampaign(BaseModel):
    """A single campaign awaiting user approval."""
    campaign_id:      str                  = Field(..., description="Campaign identifier.")
    status:           str                  = Field(..., description="Always 'ready_for_personas'.")
    ranked_companies: List[RankedCompany]  = Field(..., description="Companies awaiting approval.")
    icp_description:  Optional[str]        = Field(None, description="Original ICP brief for display.")
    created_at:       Optional[str]        = Field(None, description="ISO timestamp.")
    updated_at:       Optional[str]        = Field(None, description="ISO timestamp.")


class GetPendingCampaignsOutput(BaseModel):
    """
    All campaigns currently awaiting user approval.
    Frontend uses this on app open to restore the approval screen.
    """
    user_id:           str                  = Field(..., description="User identifier.")
    pending_campaigns: List[PendingCampaign] = Field(
        default_factory=list,
        description="List of campaigns awaiting approval, newest first.",
    )
    total_pending:     int                  = Field(
        ...,
        description="Total count of pending campaigns for this user.",
    )