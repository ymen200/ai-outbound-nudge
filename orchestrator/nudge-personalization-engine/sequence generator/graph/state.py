from typing import List, Dict, Any, Optional
from pydantic import BaseModel
from ..models.outreach_step import OutreachSequence


class GraphState(BaseModel):
    # ── Input for the graph (provided by the previous agent / caller) ──
    lead_id: str
    campaign_id: str
    entreprise: str
    contact_info: Dict[str, Any] = {}
    contexte_web: Dict[str, Any] = {}

    # ── Connection Status ──
    # When False (default), LinkedIn step 1 must be LINKEDIN_CONNECT (connection request).
    # When True, LinkedIn messages can be sent directly (LINKEDIN_MESSAGE).
    is_connected_on_linkedin: bool = False

    # ── LinkedIn InMail ──
    # When True AND is_connected_on_linkedin is False, Gemini may use LINKEDIN_INMAIL
    # (action_type) on channel "linkedin_inmail" for the first LinkedIn step instead of
    # LINKEDIN_CONNECT. Requires LinkedIn Sales Navigator / premium credits.
    has_inmail_credits: bool = False

    # ── Explicit Message Language Override ──
    # If set, overrides auto-detected language for message generation.
    # E.g., "fr" forces French messages regardless of prospect's country.
    # When None, language is auto-detected from country and use_native_language controls usage.
    message_language: Optional[str] = None

    # ── Language Detection ──
    # ASSUMPTION: Detected from contact_info location/country fields.
    # Falls back to DEFAULT_LANGUAGE if detection fails.
    detected_language: Optional[str] = None          # ISO 639-1 code: "fr", "en", "ar"
    detected_language_name: Optional[str] = None     # Display name: "French", "English"

    # ── Native Language Preference ──
    # When True, messages are generated in the prospect's detected language.
    # When False (default), messages use English regardless of detected language.
    # Explanations (timing_justification, sequence_architecture_rationale) are ALWAYS English.
    use_native_language: bool = False

    # ── Timezone Detection ──
    # ASSUMPTION: Detected from contact_info country field.
    # Used by sandbox to enforce prospect-local business hours.
    detected_timezone: Optional[int] = None          # UTC offset in hours: 1, -5, 8
    detected_timezone_name: Optional[str] = None     # Display name: "CET", "EST", "JST"

    # ── Human-in-the-Loop ──
    # ASSUMPTION: "per_sequence" is the default approval gate.
    # Controlled by the caller (Streamlit UI or API).
    approval_mode: str = "per_sequence"

    # ── Output from LLM and Validation ──
    raw_llm_output: Optional[str] = None             # Last raw response from LLM
    validated_sequence: Optional[OutreachSequence] = None  # Fully validated, sandboxed result
    validation_errors: List[str] = []                # Accumulated error strings across retries
    retry_count: int = 0                             # Current retry attempt
    sandbox_adjustments: List[Dict[str, Any]] = []   # Audit trail of any value the sandbox clipped
    fallback_triggered: bool = False                 # Flag if fallback sequence was used

    # ── Research Signals ──
    # Pre-fetched research signals from upstream modules (Detective) or demo data.
    # Forwarded to the Message Generator for personalized message generation.
    # Each signal: {"type": str, "content": str, "strength": str,
    #               "source_url": Optional[str], "timestamp": Optional[str], "why_relevant": str}
    research_signals: Optional[List[Dict[str, Any]]] = None

    # ── AI Sequence Configuration (user overrides) ──
    # Optional overrides from the frontend / orchestrator that steer Gemini's sequence design.
    # When None, Gemini decides autonomously based on prospect context.
    max_touches: Optional[int] = None
    max_days: Optional[int] = None
    preferred_first_channel: Optional[str] = None
    sequence_options: Optional[Dict[str, bool]] = None
    stage_instructions: Optional[Dict[str, str]] = None

    # ── Personality Configuration ──
    # Forwarded to the Message Generator to control message style/personality.
    # Keys match the message generator's Personality model fields.
    personality_config: Optional[Dict[str, Any]] = None

    # ── JIT Message Generation ──
    # Populated by the message_generation_node after sandboxing.
    # Each entry: {"step_number": int, "success": bool, "message": str|None,
    #              "subject": str|None, "score": int|None, "error": str|None}
    message_generation_results: List[Dict[str, Any]] = []

    # ── Strategy Output (raw Gemini strategy for debugging/audit) ──
    sequence_strategy: Optional[Dict[str, Any]] = None

    # ── Temporal Payload ──
    # Additional state for the Temporal dispatch step.
    temporal_payload: Optional[Dict[str, Any]] = None

    # ── Temporal Workflow ID ──
    # Set by dispatch_to_temporal after starting a real Temporal workflow.
    # Used for polling workflow status from the recording script.
    temporal_workflow_id: Optional[str] = None

    # ── Human Feedback (User Notes) ──
    # Runtime feedback from human-in-the-loop approval/rejection.
    # Injected into the prompt as "user notes: " to guide regeneration.
    user_feedback: Optional[str] = None
