from datetime import datetime, timedelta, timezone
from typing import Dict, Any, List
import logging
import os
from ..models.outreach_step import OutreachSequence, OutreachStep, ActionType

logger = logging.getLogger(__name__)

# --- Scheduling Constraints ---
# TEMPORARY: Reduced for recording demo. Original values:
#   MIN_WAIT_SECONDS = 3600       (1 hour)
#   MAX_WAIT_SECONDS = 1_209_600  (14 days)
MIN_WAIT_SECONDS: int = 0         # RECORDING: was 3600
MAX_WAIT_SECONDS: int = 10        # RECORDING: was 1_209_600

# ASSUMPTION: Business hours are UTC. These are also defined in models/outreach_step.py
BUSINESS_HOURS_START: int = 8  # 8 AM UTC
BUSINESS_HOURS_END: int = 18  # 6 PM UTC

# --- LLM & Retry Configuration ---
MAX_RETRIES: int = 3

# --- Sequence Length Constraint ---
# Default maximum number of touches when the caller does not specify max_touches.
# Can be overridden via the DEFAULT_MAX_TOUCHES environment variable.
# Server-side enforcement rejects sequences exceeding this limit (triggers retry/fallback).
# If changed: lower values produce shorter sequences; higher values allow longer outreach.
# The SAFE_FALLBACK_SEQUENCE (2 steps) must always be <= this value.
DEFAULT_MAX_TOUCHES: int = int(os.getenv("DEFAULT_MAX_TOUCHES", "5"))

# --- Language Detection ---
# ASSUMPTION: Default language when detection fails or location is missing.
DEFAULT_LANGUAGE: str = "en"
DEFAULT_LANGUAGE_NAME: str = "English"

# Country-to-primary-language mapping.
# Keys are lowercase country names (or common variations) extracted from location strings.
# Values are (iso_code, display_name) tuples.
# Covers the most common B2B outreach geographies. Add more entries as needed.
COUNTRY_LANGUAGE_MAP: Dict[str, tuple] = {
    # Africa
    "tunisia": ("ar", "Arabic"),
    "morocco": ("ar", "Arabic"),
    "algeria": ("ar", "Arabic"),
    "egypt": ("ar", "Arabic"),
    "senegal": ("fr", "French"),
    "ivory coast": ("fr", "French"),
    "côte d'ivoire": ("fr", "French"),
    "cameroon": ("fr", "French"),
    "nigeria": ("en", "English"),
    "kenya": ("en", "English"),
    "south africa": ("en", "English"),
    "ghana": ("en", "English"),
    # Europe
    "france": ("fr", "French"),
    "belgium": ("fr", "French"),
    "switzerland": ("fr", "French"),
    "luxembourg": ("fr", "French"),
    "monaco": ("fr", "French"),
    "germany": ("de", "German"),
    "austria": ("de", "German"),
    "spain": ("es", "Spanish"),
    "mexico": ("es", "Spanish"),
    "argentina": ("es", "Spanish"),
    "colombia": ("es", "Spanish"),
    "chile": ("es", "Spanish"),
    "peru": ("es", "Spanish"),
    "italy": ("it", "Italian"),
    "portugal": ("pt", "Portuguese"),
    "brazil": ("pt", "Portuguese"),
    "netherlands": ("nl", "Dutch"),
    "poland": ("pl", "Polish"),
    "czech republic": ("cs", "Czech"),
    "czechia": ("cs", "Czech"),
    "sweden": ("sv", "Swedish"),
    "norway": ("no", "Norwegian"),
    "denmark": ("da", "Danish"),
    "finland": ("fi", "Finnish"),
    "russia": ("ru", "Russian"),
    "ukraine": ("uk", "Ukrainian"),
    "turkey": ("tr", "Turkish"),
    "greece": ("el", "Greek"),
    "romania": ("ro", "Romanian"),
    "hungary": ("hu", "Hungarian"),
    # Middle East
    "saudi arabia": ("ar", "Arabic"),
    "uae": ("ar", "Arabic"),
    "united arab emirates": ("ar", "Arabic"),
    "qatar": ("ar", "Arabic"),
    "kuwait": ("ar", "Arabic"),
    "bahrain": ("ar", "Arabic"),
    "oman": ("ar", "Arabic"),
    "jordan": ("ar", "Arabic"),
    "lebanon": ("ar", "Arabic"),
    "israel": ("he", "Hebrew"),
    # Asia
    "china": ("zh", "Chinese"),
    "japan": ("ja", "Japanese"),
    "south korea": ("ko", "Korean"),
    "india": ("en", "English"),
    "indonesia": ("id", "Indonesian"),
    "thailand": ("th", "Thai"),
    "vietnam": ("vi", "Vietnamese"),
    "malaysia": ("ms", "Malay"),
    "philippines": ("en", "English"),
    "singapore": ("en", "English"),
    "pakistan": ("en", "English"),
    "bangladesh": ("bn", "Bengali"),
    # English-speaking
    "united states": ("en", "English"),
    "usa": ("en", "English"),
    "united kingdom": ("en", "English"),
    "uk": ("en", "English"),
    "canada": ("en", "English"),
    "australia": ("en", "English"),
    "new zealand": ("en", "English"),
    "ireland": ("en", "English"),
}

# --- Timezone Detection ---
# ASSUMPTION: Default timezone when detection fails or location is missing (UTC).
DEFAULT_TIMEZONE_OFFSET: int = 0
DEFAULT_TIMEZONE_NAME: str = "UTC"

# Country-to-timezone mapping. Keys match COUNTRY_LANGUAGE_MAP keys.
# Values are (utc_offset_hours, timezone_display_name) tuples.
# Uses approximate standard-time offsets; DST is NOT modeled.
COUNTRY_TIMEZONE_MAP: Dict[str, tuple] = {
    # Africa
    "tunisia": (1, "CET"),
    "morocco": (1, "CET"),
    "algeria": (1, "CET"),
    "egypt": (2, "EET"),
    "senegal": (0, "GMT"),
    "ivory coast": (0, "GMT"),
    "côte d'ivoire": (0, "GMT"),
    "cameroon": (1, "WAT"),
    "nigeria": (1, "WAT"),
    "kenya": (3, "EAT"),
    "south africa": (2, "SAST"),
    "ghana": (0, "GMT"),
    # Europe
    "france": (1, "CET"),
    "belgium": (1, "CET"),
    "switzerland": (1, "CET"),
    "luxembourg": (1, "CET"),
    "monaco": (1, "CET"),
    "germany": (1, "CET"),
    "austria": (1, "CET"),
    "spain": (1, "CET"),
    "italy": (1, "CET"),
    "netherlands": (1, "CET"),
    "poland": (1, "CET"),
    "czech republic": (1, "CET"),
    "czechia": (1, "CET"),
    "sweden": (1, "CET"),
    "norway": (1, "CET"),
    "denmark": (1, "CET"),
    "finland": (2, "EET"),
    "greece": (2, "EET"),
    "romania": (2, "EET"),
    "hungary": (1, "CET"),
    "russia": (3, "MSK"),
    "ukraine": (2, "EET"),
    "turkey": (3, "TRT"),
    # Americas
    "mexico": (-6, "CST"),
    "argentina": (-3, "ART"),
    "colombia": (-5, "COT"),
    "chile": (-4, "CLT"),
    "peru": (-5, "PET"),
    "brazil": (-3, "BRT"),
    "united states": (-5, "EST"),
    "usa": (-5, "EST"),
    "canada": (-5, "EST"),
    "united kingdom": (0, "GMT"),
    "uk": (0, "GMT"),
    "ireland": (0, "GMT"),
    "portugal": (0, "WET"),
    # Middle East
    "saudi arabia": (3, "AST"),
    "uae": (4, "GST"),
    "united arab emirates": (4, "GST"),
    "qatar": (3, "AST"),
    "kuwait": (3, "AST"),
    "bahrain": (3, "AST"),
    "oman": (4, "GST"),
    "jordan": (3, "EEST"),
    "lebanon": (2, "EET"),
    "israel": (2, "IST"),
    # Asia
    "china": (8, "CST"),
    "japan": (9, "JST"),
    "south korea": (9, "KST"),
    "india": (5, "IST+"),  # UTC+5:30, approximated as +5
    "indonesia": (7, "WIB"),
    "thailand": (7, "ICT"),
    "vietnam": (7, "ICT"),
    "malaysia": (8, "MYT"),
    "philippines": (8, "PST"),
    "singapore": (8, "SGT"),
    "pakistan": (5, "PKT"),
    "bangladesh": (6, "BST"),
    # Oceania
    "australia": (10, "AEST"),
    "new zealand": (12, "NZST"),
}

# --- Human-in-the-Loop Approval Modes ---
# ASSUMPTION: "per_sequence" is the default — one approval for the whole sequence plan.
# "per_step" pauses before each step execution for approval.
# "per_step_and_message" requires approval of both the step plan AND the generated message before sending.
APPROVAL_MODE_PER_SEQUENCE: str = "per_sequence"
APPROVAL_MODE_PER_STEP: str = "per_step"
APPROVAL_MODE_PER_STEP_AND_MESSAGE: str = "per_step_and_message"

APPROVAL_MODES: List[str] = [
    APPROVAL_MODE_PER_SEQUENCE,
    APPROVAL_MODE_PER_STEP,
    APPROVAL_MODE_PER_STEP_AND_MESSAGE,
]

# --- Valid Outreach Channels ---
# Single source of truth for valid channel strings used in OutreachStep.channel
VALID_CHANNELS: List[str] = [
    "email",
    "linkedin_dm",
    "linkedin_inmail",
]

# --- Safe Fallback Sequence ---
# A minimal, known-good 2-step sequence that passes all validation.
# This is used if the LLM fails to generate a valid sequence after MAX_RETRIES.
# ASSUMPTION: Default lead_id, campaign_id for fallback sequence.
SAFE_FALLBACK_SEQUENCE_DATA: Dict[str, Any] = {
    "lead_id": "fallback_lead_001",
    "campaign_id": "fallback_campaign_001",
    "generated_at": datetime.now(timezone.utc).isoformat(),
    "detected_language": DEFAULT_LANGUAGE,
    "detected_timezone": DEFAULT_TIMEZONE_OFFSET,
    "detected_timezone_name": DEFAULT_TIMEZONE_NAME,
    "approval_mode": APPROVAL_MODE_PER_SEQUENCE,
    "steps": [
        {
            "step_number": 1,
            "action_type": ActionType.LINKEDIN_CONNECT.value,
            "channel": "linkedin_dm",
            "scheduled_timestamp": (datetime.now(timezone.utc).replace(hour=BUSINESS_HOURS_START, minute=0, second=0, microsecond=0) + timedelta(days=1)).isoformat(),
            "wait_delay_seconds": 0,
            "timing_justification": "First touch, immediate connection request.",
            "sequence_architecture_rationale": "Initiate connection to establish basic relationship.",
            "message_language": DEFAULT_LANGUAGE,
        },
        {
            "step_number": 2,
            "action_type": ActionType.EMAIL_1.value,
            "channel": "email",
            "scheduled_timestamp": (datetime.now(timezone.utc).replace(hour=BUSINESS_HOURS_START, minute=0, second=0, microsecond=0) + timedelta(days=3)).isoformat(),
            "wait_delay_seconds": timedelta(days=2).total_seconds(),
            "timing_justification": "Follow-up after initial connection attempt.",
            "sequence_architecture_rationale": "Provide more context via email if LinkedIn connect is unaccepted.",
            "message_language": DEFAULT_LANGUAGE,
        }
    ]
}

# Validate the fallback sequence on load to ensure it's always valid.
try:
    now_utc = datetime.now(timezone.utc)
    fallback_start_date = (now_utc + timedelta(days=1))
    while fallback_start_date.weekday() >= 5:
        fallback_start_date += timedelta(days=1)
    fallback_start_date = fallback_start_date.replace(hour=BUSINESS_HOURS_START, minute=0, second=0, microsecond=0)

    SAFE_FALLBACK_SEQUENCE_DATA["steps"][0]["scheduled_timestamp"] = fallback_start_date.isoformat()
    SAFE_FALLBACK_SEQUENCE_DATA["steps"][1]["scheduled_timestamp"] = (fallback_start_date + timedelta(days=2)).isoformat()
    SAFE_FALLBACK_SEQUENCE = OutreachSequence.model_validate(SAFE_FALLBACK_SEQUENCE_DATA)
except Exception as e:
    logger.critical(f"SAFE_FALLBACK_SEQUENCE is invalid: {e}")
    SAFE_FALLBACK_SEQUENCE = None


__all__ = [
    "MIN_WAIT_SECONDS",
    "MAX_WAIT_SECONDS",
    "BUSINESS_HOURS_START",
    "BUSINESS_HOURS_END",
    "MAX_RETRIES",
    "SAFE_FALLBACK_SEQUENCE",
    "DEFAULT_LANGUAGE",
    "DEFAULT_LANGUAGE_NAME",
    "COUNTRY_LANGUAGE_MAP",
    "APPROVAL_MODES",
    "APPROVAL_MODE_PER_SEQUENCE",
    "APPROVAL_MODE_PER_STEP",
    "APPROVAL_MODE_PER_STEP_AND_MESSAGE",
    "VALID_CHANNELS",
    "COUNTRY_TIMEZONE_MAP",
    "DEFAULT_TIMEZONE_OFFSET",
    "DEFAULT_TIMEZONE_NAME",
    "DEFAULT_MAX_TOUCHES",
]
