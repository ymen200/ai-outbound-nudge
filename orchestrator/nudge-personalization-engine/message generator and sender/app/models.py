from typing import List, Optional, Dict, Any
from pydantic import BaseModel, Field, model_validator
from enum import Enum

# ----------------------------
# ENUMS
# ----------------------------

class Status(str, Enum):
    PLANNING = "planning"
    RESEARCHING = "researching"
    STRATEGIZING = "strategizing"
    WRITING = "writing"
    REVISING = "revising"
    VALIDATING = "validating"
    AWAITING_HUMAN = "awaiting_human"
    COMPLETE = "complete"
    FAILED = "failed"

class ActionType(str, Enum):
    SAVE_DRAFT = "save_draft"
    SEND_NOW = "send_now"
    RETRY = "retry"
    HUMAN_REVIEW = "human_review"
    ABORT = "abort"

class Channel(str, Enum):
    LINKEDIN_DM = "linkedin_dm"
    LINKEDIN_INMAIL = "linkedin_inmail"
    EMAIL = "email"

class Intent(str, Enum):
    DIRECT_OUTREACH = "direct_outreach"
    FOLLOW_UP = "follow_up"
    REFERRAL = "referral"
    RE_ENGAGEMENT = "re_engagement"
    EVENT_BASED = "event_based"

class Stage(str, Enum):
    FIRST_TOUCH = "first_touch"
    SECOND_TOUCH = "second_touch"
    THIRD_TOUCH = "third_touch"

class BaseTemplate(str, Enum):
    SOFT_SELL = "soft_sell"
    VALUE_BASED = "value_based"
    SPIN_SELLING = "spin_selling"
    DIRECT = "direct"
    CONSULTATIVE = "consultative"
    CUSTOM = "custom"

# ----------------------------
# PERSONALITY BLOCK
# ----------------------------

class Personality(BaseModel):
    base_template: BaseTemplate = BaseTemplate.SOFT_SELL

    # Optional override for the base template
    custom_template_description: Optional[str] = Field(
        None,
        description="Describe a custom tone/style if base_template isn't enough"
    )

    # Trait list e.g. ["empathetic", "direct", "curious"]
    personality_traits: List[str] = Field(
        default=[],
        description="Adjectives that define how the sender comes across"
    )

    # Phrases the writer must include somewhere
    always_include_phrases: List[str] = Field(
        default=[],
        description="Phrases or words that must appear in the message"
    )

    # Phrases the writer must never use
    never_use_phrases: List[str] = Field(
        default=[],
        description="Banned words or phrases"
    )

    # How many distinct value points to hit in one message
    touchdowns_per_message: int = Field(
        default=2,
        ge=1,
        le=5,
        description="Number of distinct value/hook touchpoints to hit in the message"
    )

    # Which hook types are allowed e.g. ["recent_post", "company_news", "job_change"]
    enabled_hook_types: List[str] = Field(
        default=[],
        description="Which signal types can be used as hooks"
    )

    # Scales 1-10
    urgency_level: int = Field(
        default=3,
        ge=1,
        le=10,
        description="How urgent the message feels. 1=no urgency, 10=extremely urgent"
    )

    self_deprecation: int = Field(
        default=1,
        ge=1,
        le=10,
        description="How much self-deprecating humor to include. 1=none, 10=a lot"
    )

    humor_sarcasm: int = Field(
        default=3,
        ge=1,
        le=10,
        description="How much humor or light sarcasm. 1=very serious, 10=very funny"
    )

    # Per-stage overrides e.g. {"second_touch": "be more direct"}
    stage_instructions: Dict[str, str] = Field(
        default={},
        description="Stage-specific instruction overrides keyed by stage name"
    )

    # Past messages written by the sender — used to emulate their voice
    voice_samples: List[str] = Field(
        default=[],
        description="3-5 real messages previously written by the sender. The writer will analyze and match their natural style, vocabulary, and tone."
    )

# ----------------------------
# COMPANY DETAILS BLOCK
# ----------------------------

class CompanyDetails(BaseModel):
    company_name: str = Field(..., description="Sender's company name")
    website: Optional[str] = Field(None, description="Company website URL")
    industry: Optional[str] = Field(None, description="Industry the company operates in")
    elevator_pitch: Optional[str] = Field(
        None,
        description="One to two sentence pitch of what the company does"
    )
    value_props: List[str] = Field(
        default=[],
        description="List of core value propositions"
    )
    social_proof: List[str] = Field(
        default=[],
        description="Testimonials, logos, metrics, case studies"
    )

# ----------------------------
# SELECTED OFFER BLOCK
# ----------------------------

class SelectedOffer(BaseModel):
    offer_name: str = Field(..., description="Name of the specific offer or product being pitched")
    pain_points: List[str] = Field(
        default=[],
        description="Pain points this offer solves"
    )
    solution_summary: Optional[str] = Field(
        None,
        description="Brief description of how the offer solves the pain"
    )
    proof_points: List[str] = Field(
        default=[],
        description="Specific results, metrics or case studies for this offer"
    )
    cta: Optional[str] = Field(
        None,
        description="The exact call to action to use e.g. 'Book a 15 min call'"
    )

# ----------------------------
# PROSPECT BLOCK (stays as before)
# ----------------------------

class Signal(BaseModel):
    type: str
    content: str
    strength: str
    source_url: Optional[str] = None
    timestamp: Optional[str] = None
    why_relevant: str

class Strategy(BaseModel):
    primary_hook: Optional[str] = None
    secondary_hook: Optional[str] = None
    angle: str = ""
    tone: str = ""
    cta_style: str = ""
    reasoning: str = ""

    @model_validator(mode="before")
    @classmethod
    def _coerce_none_strings(cls, data: Any) -> Any:
        """Coerce None values to empty strings for string fields."""
        if isinstance(data, dict):
            for field_name in ("primary_hook", "secondary_hook", "angle", "tone", "cta_style", "reasoning"):
                if data.get(field_name) is None:
                    data[field_name] = ""
        return data

class SentenceAttribution(BaseModel):
    text: str
    driven_by: List[str]
    purpose: str

class MessageDraft(BaseModel):
    body: str
    subject: Optional[str] = None
    sentence_attribution: List[SentenceAttribution] = []

class Validation(BaseModel):
    valid: bool = False
    score: int = 0
    warnings: List[str] = []
    suggested_fixes: Optional[str] = None

# ----------------------------
# HUMAN REVIEW MODELS
# ----------------------------

class HumanDecision(BaseModel):
    approved: bool = Field(..., description="True to send, False to reject and rewrite")
    feedback: Optional[str] = Field(
        None,
        description="If rejected, explain what to fix. If approved with email/linkedin channel, optionally override recipient."
    )
    prospect_email: Optional[str] = Field(None, description="Required for email send")
    prospect_linkedin_id: Optional[str] = Field(None, description="Unipile account ID for LinkedIn send")

class ReviewResponse(BaseModel):
    task_id: str
    prospect: str
    company: str
    channel: str
    message: str
    subject: Optional[str]
    score: int
    warnings: List[str]

# ----------------------------
# ROOT REQUEST MODEL
# ----------------------------

class GenerateRequest(BaseModel):
    # Who we're targeting
    target_prospect: str = Field(..., description="Full name of the prospect")
    target_company: str = Field(..., description="Prospect's company name")
    prospect_role: Optional[str] = Field(None, description="Prospect's job title")

    # Channel and intent context
    channel: Channel = Field(
        Channel.LINKEDIN_DM,
        description="The platform/channel this message will be sent on"
    )
    intent: Intent = Field(
        Intent.DIRECT_OUTREACH,
        description="The purpose/intent of this outreach"
    )
    stage: Stage = Field(
        Stage.FIRST_TOUCH,
        description="Where in the outreach sequence this message sits"
    )

    # Style configuration
    personality: Personality = Field(
        default_factory=Personality,
        description="Full personality and style configuration"
    )

    # Sender company info
    company_details: CompanyDetails = Field(
        ...,
        description="Information about the sender's company"
    )

    # What we're pitching
    selected_offer: SelectedOffer = Field(
        ...,
        description="The specific offer or product being pitched"
    )

    # Optional pre-researched signals (from external modules like Detective)
    research_signals: Optional[List[Signal]] = Field(
        None,
        description="Pre-fetched research signals. If provided, the Researcher agent will skip fetching."
    )

    # Human feedback / user notes injected at runtime into the writer prompt
    user_feedback: Optional[str] = Field(
        None,
        description="Human notes to guide message generation. Injected as 'user notes: ' in the writer prompt."
    )

# ----------------------------
# AGENT STATE
# ----------------------------

class AgentState(BaseModel):
    task_id: str
    status: Status = Status.PLANNING

    # Prospect context
    target_prospect: str
    target_company: str
    prospect_role: Optional[str] = None

    # Full request config stored on state
    channel: Channel = Channel.LINKEDIN_DM
    intent: Intent = Intent.DIRECT_OUTREACH
    stage: Stage = Stage.FIRST_TOUCH
    personality: Personality = Field(default_factory=Personality)
    company_details: Optional[CompanyDetails] = None
    selected_offer: Optional[SelectedOffer] = None

    # Pipeline data
    memory: Dict[str, Any] = {}
    research_signals: List[Signal] = []
    strategy: Optional[Strategy] = None
    draft: Optional[MessageDraft] = None
    validation: Optional[Validation] = None

    # Human feedback / user notes forwarded from the request
    user_feedback: Optional[str] = None

    # Output language (ISO 639-1 code, e.g. "en", "fr")
    language: Optional[str] = None

    # Control
    next_action: Optional[Dict[str, Any]] = None
    iteration_count: int = 0
    max_iterations: int = 3