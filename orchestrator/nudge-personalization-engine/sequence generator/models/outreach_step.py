from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import List, Optional, Dict, Any

from pydantic import BaseModel, Field, ValidationError, field_validator, model_validator


class ActionType(str, Enum):
    LINKEDIN_CONNECT = "LINKEDIN_CONNECT"
    LINKEDIN_MESSAGE = "LINKEDIN_MESSAGE"
    LINKEDIN_INMAIL = "LINKEDIN_INMAIL"
    EMAIL_1 = "EMAIL_1"


# Valid outreach channels — single source of truth used by validators
VALID_CHANNEL_VALUES = frozenset({
    "email",
    "linkedin_dm",
    "linkedin_inmail",
})

# ASSUMPTION: Business hours and weekend definitions are UTC.
BUSINESS_HOURS_START = 8  # 8 AM UTC
BUSINESS_HOURS_END = 18   # 6 PM UTC


class OutreachStep(BaseModel):
    step_number: int = Field(..., ge=1)
    action_type: ActionType
    channel: str = Field(
        ...,
        description="The outreach channel for this step (email, linkedin_dm, linkedin_inmail)."
    )
    scheduled_timestamp: datetime = Field(
        ...,
        description="ISO-8601 UTC timestamp, must be within business hours and not on a weekend."
    )
    wait_delay_seconds: int = Field(
        ...,
        ge=0,
        description="Delay from the *previous* step in seconds. Must be >= 0."
    )
    timing_justification: str = Field(
        ...,
        min_length=10,
        description="Explanation for chosen timing."
    )
    sequence_architecture_rationale: str = Field(
        ...,
        min_length=10,
        description="Explanation for action placement in sequence."
    )

    # --- Language & JIT Generation Fields ---
    # ASSUMPTION: message_language defaults to the sequence-level detected_language
    # if not explicitly set per step.
    message_language: Optional[str] = Field(
        default=None,
        description="ISO 639-1 language code for this step's message (e.g., 'fr', 'en', 'ar'). "
                    "If None, falls back to the sequence-level detected_language."
    )

    # ASSUMPTION: step_context carries the data needed for just-in-time message
    # generation. It is populated by the sequence generator and consumed by the
    # message generation node / Temporal activity. No further mutation after sandbox.
    step_context: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Context payload for JIT message generation. Includes prospect details, "
                    "offer info, company details, stage, and any research signals."
    )

    @field_validator("channel")
    @classmethod
    def validate_channel(cls, v: str) -> str:
        """Reject channels not in the canonical set."""
        if v not in VALID_CHANNEL_VALUES:
            raise ValueError(
                f"Invalid channel '{v}'. Must be one of: {sorted(VALID_CHANNEL_VALUES)}."
            )
        return v

    @field_validator("scheduled_timestamp")
    @classmethod
    def check_business_hours_and_weekends(cls, v: datetime) -> datetime:
        # Ensure timestamp is timezone-aware and in UTC
        if v.tzinfo is None:
            raise ValueError("scheduled_timestamp must be timezone-aware (UTC).")
        if v.tzinfo != timezone.utc:
            v = v.astimezone(timezone.utc)

        # NOTE: We intentionally do NOT enforce business hours here.
        # The sandbox node is the authoritative enforcer — it adjusts timestamps
        # to the prospect's LOCAL business hours (which vary by timezone).
        # A UTC-only check would break for non-UTC prospects (e.g., EST local 6pm = 23:00 UTC).

        return v


class OutreachSequence(BaseModel):
    lead_id: str
    campaign_id: str
    generated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    steps: List[OutreachStep]

    # --- Language Detection ---
    # ASSUMPTION: detected_language is the primary language for the sequence.
    # Individual steps may override via OutreachStep.message_language.
    detected_language: Optional[str] = Field(
        default=None,
        description="ISO 639-1 code for the prospect's detected primary language "
                    "(e.g., 'fr' for French, 'en' for English). Derived from location data."
    )

    # --- Timezone ---
    # ASSUMPTION: detected_timezone is the prospect's UTC offset in hours.
    # Used by the sandbox to enforce local business hours and by Temporal for display.
    detected_timezone: Optional[int] = Field(
        default=None,
        description="Prospect's UTC timezone offset in hours (e.g., 1 for CET, -5 for EST). "
                    "Used to schedule messages during the prospect's local business hours."
    )
    detected_timezone_name: Optional[str] = Field(
        default=None,
        description="Human-readable timezone name (e.g., 'CET', 'EST', 'JST')."
    )

    # --- Approval Mode ---
    # ASSUMPTION: per_sequence is the safest default — one human approval gate
    # before any step executes.
    approval_mode: str = Field(
        default="per_sequence",
        description="Human-in-the-loop approval mode. One of: "
                    "'per_sequence' (approve entire plan once), "
                    "'per_step' (approve before each step), "
                    "'per_step_and_message' (approve step plan AND generated message before send)."
    )

    @field_validator("approval_mode")
    @classmethod
    def validate_approval_mode(cls, v: str) -> str:
        valid = {"per_sequence", "per_step", "per_step_and_message"}
        if v not in valid:
            raise ValueError(
                f"Invalid approval_mode '{v}'. Must be one of: {sorted(valid)}."
            )
        return v

    @model_validator(mode="after")
    def check_sequence_integrity(self):
        if not self.steps:
            return self

        # Check for strictly increasing and contiguous step_numbers
        for i, step in enumerate(self.steps):
            expected_step_number = i + 1
            if step.step_number != expected_step_number:
                raise ValueError(
                    f"Step numbers must be strictly increasing and contiguous starting from 1. "
                    f"Expected step_number {expected_step_number}, got {step.step_number}."
                )

        # Check for strictly increasing scheduled_timestamps
        for i in range(1, len(self.steps)):
            if self.steps[i].scheduled_timestamp <= self.steps[i - 1].scheduled_timestamp:
                raise ValueError(
                    f"scheduled_timestamp for step {self.steps[i].step_number} "
                    f"({self.steps[i].scheduled_timestamp}) must be strictly greater than "
                    f"previous step ({self.steps[i - 1].scheduled_timestamp})."
                )
        return self
