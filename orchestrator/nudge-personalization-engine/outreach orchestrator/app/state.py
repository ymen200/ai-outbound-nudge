"""OrchestratorState — the LangGraph state schema for the Outreach Orchestrator."""

from typing import List, Dict, Any, Optional
from pydantic import BaseModel


class OrchestratorState(BaseModel):
    # ── Input (mirrors Sequence Generator GraphState) ──
    lead_id: str
    campaign_id: str
    entreprise: str
    contact_info: Dict[str, Any] = {}
    contexte_web: Dict[str, Any] = {}
    research_signals: Optional[List[Dict[str, Any]]] = None
    is_connected_on_linkedin: bool = False
    has_inmail_credits: bool = False  # LinkedIn InMail credits available (Sales Navigator / premium)
    use_native_language: bool = False
    message_language: Optional[str] = None
    approval_mode: str = "per_sequence"

    # ── Sender info (for Sequence Generator request) ──
    sender_company: str = "My Company"
    sender_elevator_pitch: str = ""
    offer_name: str = "Default Offer"
    solution_summary: str = ""
    cta: str = ""

    # ── AI Sequence Configuration (user overrides) ──
    max_touches: Optional[int] = None
    max_days: Optional[int] = None
    preferred_first_channel: Optional[str] = None
    sequence_options: Optional[Dict[str, bool]] = None
    stage_instructions: Optional[Dict[str, str]] = None

    # ── Personality Configuration (forwarded to Message Generator) ──
    personality_config: Optional[Dict[str, Any]] = None

    # ── Orchestration state ──
    sequence_result: Optional[Dict[str, Any]] = None
    message_results: Optional[Dict[str, Any]] = None
    observability_snapshot: Optional[Dict[str, Any]] = None

    # ── Global orchestrator interaction ──
    feedback: Optional[str] = None
    config_overrides: Optional[Dict[str, Any]] = None
    debug_mode: bool = True  # Propagated to modules: bypass memory for deterministic runs

    # ── Output ──
    status: str = "pending"  # pending | running | completed | failed
    errors: List[str] = []
    generation_time_seconds: float = 0.0
