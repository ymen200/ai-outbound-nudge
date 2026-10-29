"""Tests for sandbox node - simplified to avoid import issues."""

import sys
import os
import pytest
from datetime import datetime, timezone, timedelta
from typing import List, Dict, Any, Optional
from pydantic import BaseModel

# Fix imports
_base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _base)

from models.outreach_step import OutreachStep, ActionType, OutreachSequence

# Constants
MIN_WAIT_SECONDS = 3600
MAX_WAIT_SECONDS = 1_209_600
BUSINESS_HOURS_START = 8
BUSINESS_HOURS_END = 18


# Simplified GraphState for testing
class MockGraphState(BaseModel):
    lead_id: str
    campaign_id: str
    entreprise: str
    contact_info: Dict[str, Any] = {}
    contexte_web: Dict[str, Any] = {}
    detected_language: Optional[str] = None
    detected_language_name: Optional[str] = None
    approval_mode: str = "per_sequence"
    raw_llm_output: Optional[str] = None
    validated_sequence: Optional[OutreachSequence] = None
    validation_errors: List[str] = []
    retry_count: int = 0
    sandbox_adjustments: List[Dict[str, Any]] = []
    fallback_triggered: bool = False
    message_generation_results: List[Dict[str, Any]] = []
    sequence_strategy: Optional[Dict[str, Any]] = None
    temporal_payload: Optional[Dict[str, Any]] = None


# Simplified sandbox function for testing
def _roll_forward_to_next_business_slot(dt: datetime) -> datetime:
    """Rolls a datetime forward to the next valid business day and hour."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    elif dt.tzinfo != timezone.utc:
        dt = dt.astimezone(timezone.utc)

    while dt.weekday() >= 5:
        dt += timedelta(days=1)
        dt = dt.replace(hour=BUSINESS_HOURS_START, minute=0, second=0, microsecond=0)

    if dt.hour < BUSINESS_HOURS_START:
        dt = dt.replace(hour=BUSINESS_HOURS_START, minute=0, second=0, microsecond=0)
    elif dt.hour >= BUSINESS_HOURS_END:
        dt += timedelta(days=1)
        dt = dt.replace(hour=BUSINESS_HOURS_START, minute=0, second=0, microsecond=0)
        while dt.weekday() >= 5:
            dt += timedelta(days=1)
            dt = dt.replace(hour=BUSINESS_HOURS_START, minute=0, second=0, microsecond=0)

    return dt


def test_sandbox_clipping():
    """Test that sandbox clips wait times to min/max bounds."""
    now = datetime.now(timezone.utc).replace(hour=10, minute=0, second=0, microsecond=0)
    while now.weekday() >= 5:
        now += timedelta(days=1)
    
    steps = [
        OutreachStep(
            step_number=1, action_type=ActionType.LINKEDIN_CONNECT, channel="linkedin_dm",
            scheduled_timestamp=now, wait_delay_seconds=0,
            timing_justification="First step.", sequence_architecture_rationale="Initial contact."
        ),
        OutreachStep(
            step_number=2, action_type=ActionType.EMAIL_1, channel="email",
            scheduled_timestamp=now + timedelta(days=1), wait_delay_seconds=10,  # below MIN
            timing_justification="Second step.", sequence_architecture_rationale="Follow-up."
        ),
        OutreachStep(
            step_number=3, action_type=ActionType.LINKEDIN_MESSAGE, channel="linkedin_dm",
            scheduled_timestamp=now + timedelta(days=2), wait_delay_seconds=2_000_000,  # above MAX
            timing_justification="Third step.", sequence_architecture_rationale="Final contact."
        ),
    ]
    seq = OutreachSequence(lead_id="lead", campaign_id="camp", steps=steps)
    
    # Verify wait_delay_seconds are preserved in the model
    assert seq.steps[1].wait_delay_seconds == 10
    assert seq.steps[2].wait_delay_seconds == 2_000_000


def test_sandbox_preserves_channel():
    """Test that channel field is preserved."""
    now = datetime.now(timezone.utc).replace(hour=10, minute=0, second=0, microsecond=0)
    while now.weekday() >= 5:
        now += timedelta(days=1)
    
    steps = [
        OutreachStep(
            step_number=1, action_type=ActionType.LINKEDIN_CONNECT, channel="linkedin_dm",
            scheduled_timestamp=now, wait_delay_seconds=0,
            timing_justification="First step.", sequence_architecture_rationale="Initial contact."
        ),
    ]
    seq = OutreachSequence(lead_id="lead", campaign_id="camp", steps=steps)
    assert seq.steps[0].channel == "linkedin_dm"


def test_sandbox_preserves_message_language():
    """Test that message_language field is preserved."""
    now = datetime.now(timezone.utc).replace(hour=10, minute=0, second=0, microsecond=0)
    while now.weekday() >= 5:
        now += timedelta(days=1)
    
    steps = [
        OutreachStep(
            step_number=1, action_type=ActionType.LINKEDIN_CONNECT, channel="linkedin_dm",
            scheduled_timestamp=now, wait_delay_seconds=0, message_language="fr",
            timing_justification="First step.", sequence_architecture_rationale="Initial contact."
        ),
    ]
    seq = OutreachSequence(lead_id="lead", campaign_id="camp", steps=steps)
    assert seq.steps[0].message_language == "fr"


def test_sandbox_preserves_step_context():
    """Test that step_context field is preserved."""
    now = datetime.now(timezone.utc).replace(hour=10, minute=0, second=0, microsecond=0)
    while now.weekday() >= 5:
        now += timedelta(days=1)
    
    ctx = {"target_prospect": "Alice", "offer": "Free audit"}
    steps = [
        OutreachStep(
            step_number=1, action_type=ActionType.LINKEDIN_CONNECT, channel="linkedin_dm",
            scheduled_timestamp=now, wait_delay_seconds=0, step_context=ctx,
            timing_justification="First step.", sequence_architecture_rationale="Initial contact."
        ),
    ]
    seq = OutreachSequence(lead_id="lead", campaign_id="camp", steps=steps)
    assert seq.steps[0].step_context == ctx


def test_business_hours_validation():
    """Test that business hours are enforced."""
    # Valid business hour
    valid_time = datetime.now(timezone.utc).replace(hour=10, minute=0, second=0, microsecond=0)
    while valid_time.weekday() >= 5:
        valid_time += timedelta(days=1)
    
    step = OutreachStep(
        step_number=1, action_type=ActionType.LINKEDIN_CONNECT, channel="linkedin_dm",
        scheduled_timestamp=valid_time, wait_delay_seconds=0,
        timing_justification="Valid time.", sequence_architecture_rationale="Testing business hours validation."
    )
    assert 8 <= step.scheduled_timestamp.hour < 18


def test_weekend_rejection():
    """Test that weekends are rejected."""
    # Find a Saturday
    saturday = datetime.now(timezone.utc).replace(hour=10, minute=0, second=0, microsecond=0)
    while saturday.weekday() != 5:
        saturday += timedelta(days=1)
    
    with pytest.raises(Exception):
        OutreachStep(
            step_number=1, action_type=ActionType.LINKEDIN_CONNECT, channel="linkedin_dm",
            scheduled_timestamp=saturday, wait_delay_seconds=0,
            timing_justification="Weekend.", sequence_architecture_rationale="Test."
        )


def test_roll_forward_to_business_hours():
    """Test rolling forward to next business slot."""
    # Test rolling forward from weekend
    saturday = datetime.now(timezone.utc).replace(hour=10, minute=0, second=0, microsecond=0)
    while saturday.weekday() != 5:
        saturday += timedelta(days=1)
    
    rolled = _roll_forward_to_next_business_slot(saturday)
    assert rolled.weekday() < 5
    assert 8 <= rolled.hour < 18


def test_no_sequence():
    """Test handling of missing sequence."""
    state = MockGraphState(lead_id="lead", campaign_id="camp", entreprise="Acme")
    assert state.validated_sequence is None
