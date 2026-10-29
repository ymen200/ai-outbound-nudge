"""Tests for OutreachStep and OutreachSequence models."""

import sys
import os
import pytest
from datetime import datetime, timezone, timedelta

# Fix imports: the directory has a space, so we need sys.path manipulation
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from models.outreach_step import (
    OutreachStep, ActionType, OutreachSequence, VALID_CHANNEL_VALUES
)


def _make_step(step_number=1, channel="linkedin_dm", **kwargs):
    """Helper to create a valid OutreachStep."""
    now = datetime.now(timezone.utc).replace(hour=10, minute=0, second=0, microsecond=0)
    # Roll forward to next business day if on weekend
    while now.weekday() >= 5:
        now += timedelta(days=1)
    defaults = {
        "step_number": step_number,
        "action_type": ActionType.LINKEDIN_CONNECT,
        "channel": channel,
        "scheduled_timestamp": now,
        "wait_delay_seconds": 0,
        "timing_justification": "Initial contact after research.",
        "sequence_architecture_rationale": "First touch to establish connection."
    }
    defaults.update(kwargs)
    return OutreachStep(**defaults)


def test_outreach_step_valid():
    step = _make_step()
    assert step.step_number == 1
    assert step.action_type == ActionType.LINKEDIN_CONNECT
    assert step.channel == "linkedin_dm"


def test_outreach_step_with_language():
    step = _make_step(message_language="fr")
    assert step.message_language == "fr"


def test_outreach_step_with_step_context():
    ctx = {"target_prospect": "Alice", "target_company": "Acme"}
    step = _make_step(step_context=ctx)
    assert step.step_context == ctx
    assert step.step_context["target_prospect"] == "Alice"


def test_outreach_step_invalid_action():
    with pytest.raises(Exception):
        _make_step(action_type="INVALID_ACTION")


def test_outreach_step_invalid_channel():
    with pytest.raises(Exception):
        _make_step(channel="fax")


def test_outreach_step_valid_channels():
    for ch in VALID_CHANNEL_VALUES:
        step = _make_step(channel=ch)
        assert step.channel == ch


def test_outreach_sequence_integrity():
    now = datetime.now(timezone.utc).replace(hour=10, minute=0, second=0, microsecond=0)
    while now.weekday() >= 5:
        now += timedelta(days=1)
    steps = [
        _make_step(step_number=1, scheduled_timestamp=now),
        OutreachStep(
            step_number=2,
            action_type=ActionType.EMAIL_1,
            channel="email",
            scheduled_timestamp=now + timedelta(days=2),
            wait_delay_seconds=172800,
            timing_justification="Follow-up email after connection.",
            sequence_architecture_rationale="Provide more context via email."
        ),
    ]
    seq = OutreachSequence(lead_id="lead1", campaign_id="camp1", steps=steps)
    assert len(seq.steps) == 2
    assert seq.steps[1].step_number == 2


def test_outreach_sequence_with_language():
    now = datetime.now(timezone.utc).replace(hour=10, minute=0, second=0, microsecond=0)
    while now.weekday() >= 5:
        now += timedelta(days=1)
    steps = [_make_step(step_number=1, scheduled_timestamp=now, message_language="fr")]
    seq = OutreachSequence(
        lead_id="lead1", campaign_id="camp1", steps=steps,
        detected_language="fr", approval_mode="per_step"
    )
    assert seq.detected_language == "fr"
    assert seq.approval_mode == "per_step"


def test_outreach_sequence_invalid_approval_mode():
    now = datetime.now(timezone.utc).replace(hour=10, minute=0, second=0, microsecond=0)
    while now.weekday() >= 5:
        now += timedelta(days=1)
    steps = [_make_step(step_number=1, scheduled_timestamp=now)]
    with pytest.raises(Exception):
        OutreachSequence(
            lead_id="lead1", campaign_id="camp1", steps=steps,
            approval_mode="invalid_mode"
        )


def test_outreach_sequence_default_approval_mode():
    now = datetime.now(timezone.utc).replace(hour=10, minute=0, second=0, microsecond=0)
    while now.weekday() >= 5:
        now += timedelta(days=1)
    steps = [_make_step(step_number=1, scheduled_timestamp=now)]
    seq = OutreachSequence(lead_id="lead1", campaign_id="camp1", steps=steps)
    assert seq.approval_mode == "per_sequence"
