"""Unit tests for custom sequence, ai_write validator, and structured DB persistence."""

import json
import os
import tempfile
import pytest

# ── Fixtures ──────────────────────────────────────────────────────────

@pytest.fixture
def temp_db():
    """CampaignStore backed by a temp SQLite file."""
    from app.store import CampaignStore
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    store = CampaignStore(db_path=path)
    yield store
    if os.path.exists(path):
        os.remove(path)


@pytest.fixture
def campaign_id(temp_db):
    """Create a minimal campaign and return its ID."""
    cid = temp_db.create_campaign(
        user_id="test-user",
        raw_icp="test icp",
        user_offering="test offering",
        outreach_config={"approval_mode": "per_sequence"},
    )
    return cid


# ── ai_write validator tests ──────────────────────────────────────────

def test_ai_write_true_allows_empty_message():
    """When ai_write=True, the model validator should skip the message-required check."""
    from app.api import CustomSequenceStep
    step = CustomSequenceStep(
        step_num=1,
        action_type="EMAIL_1",
        channel="email",
        message="",
        ai_write=True,
    )
    assert step.ai_write is True
    assert step.message == ""
    assert step.action_type == "EMAIL_1"


def test_ai_write_false_rejects_empty_message_for_text_channel():
    """When ai_write=False and it's a text channel, empty message should raise."""
    from app.api import CustomSequenceStep
    from pydantic import ValidationError
    with pytest.raises(ValidationError):
        CustomSequenceStep(
            step_num=1,
            action_type="EMAIL_1",
            channel="email",
            message="",
            ai_write=False,
        )


def test_ai_write_false_rejects_empty_message_for_linkedin_dm():
    """LINKEDIN_DM is also a text channel — requires message when ai_write=False."""
    from app.api import CustomSequenceStep
    from pydantic import ValidationError
    with pytest.raises(ValidationError):
        CustomSequenceStep(
            step_num=2,
            action_type="LINKEDIN_DM",
            channel="linkedin_dm",
            message="  ",
            ai_write=False,
        )


def test_ai_write_defaults_to_false():
    """ai_write should default to False."""
    from app.api import CustomSequenceStep
    step = CustomSequenceStep(
        step_num=1,
        action_type="EMAIL_1",
        channel="email",
        message="Hello",
    )
    assert step.ai_write is False


def test_linkedin_connect_allows_empty_message_regardless_of_ai_write():
    """LINKEDIN_CONNECT steps may always omit a message."""
    from app.api import CustomSequenceStep
    step = CustomSequenceStep(
        step_num=1,
        action_type="LINKEDIN_CONNECT",
        channel="linkedin_dm",
        message="",
        ai_write=False,
    )
    assert step.step_num == 1
    assert step.message == ""


def test_ai_write_true_allows_empty_message_for_linkedin_inmail():
    """LINKEDIN_INMAIL with ai_write=True should allow empty message."""
    from app.api import CustomSequenceStep
    step = CustomSequenceStep(
        step_num=1,
        action_type="LINKEDIN_INMAIL",
        channel="linkedin_inmail",
        message="",
        ai_write=True,
    )
    assert step.ai_write is True


# ── CustomSequenceStep field tests ────────────────────────────────────

def test_custom_sequence_step_all_fields():
    """All fields should be captured correctly."""
    from app.api import CustomSequenceStep
    step = CustomSequenceStep(
        step_num=3,
        action_type="EMAIL_1",
        channel="email",
        wait_delay_seconds=86400,
        message="Bonjour!",
        ai_write=False,
        subject="Quick question",
        day_offset=2,
        time_of_day="14h",
        strategy_notes="Follow-up after LinkedIn connection",
    )
    assert step.step_num == 3
    assert step.action_type == "EMAIL_1"
    assert step.channel == "email"
    assert step.wait_delay_seconds == 86400
    assert step.message == "Bonjour!"
    assert step.ai_write is False
    assert step.subject == "Quick question"
    assert step.day_offset == 2
    assert step.time_of_day == "14h"
    assert step.strategy_notes == "Follow-up after LinkedIn connection"


def test_custom_sequence_step_model_dump():
    """model_dump() should include all fields including ai_write."""
    from app.api import CustomSequenceStep
    step = CustomSequenceStep(
        step_num=1,
        action_type="LINKEDIN_DM",
        channel="linkedin_dm",
        message="Hey!",
        ai_write=False,
    )
    dumped = step.model_dump()
    assert "ai_write" in dumped
    assert dumped["ai_write"] is False
    assert dumped["step_num"] == 1
    assert dumped["message"] == "Hey!"


# ── outreach_sequence_steps DB persistence tests ────────────────────

def test_save_and_list_outreach_steps(temp_db, campaign_id):
    """Steps should be persisted as structured rows and retrievable."""
    workflow_id = "wf_123"
    steps = [
        {
            "step_num": 1,
            "action_type": "EMAIL_1",
            "channel": "email",
            "message": {"message": "Hello there!", "subject": "Hey", "warnings": []},
            "ai_write": False,
            "status": "sent",
            "quality_score": 85,
            "wait_delay_seconds": 0,
        },
        {
            "step_num": 2,
            "action_type": "LINKEDIN_DM",
            "channel": "linkedin_dm",
            "message": {"message": "", "subject": None, "warnings": []},
            "ai_write": True,
            "status": "pending",
            "wait_delay_seconds": 172800,
        },
    ]
    temp_db.save_outreach_steps(campaign_id, workflow_id, thread_id="thread_abc", steps=steps)

    rows = temp_db.list_outreach_steps(campaign_id)
    assert len(rows) == 2

    step1 = rows[0]
    assert step1["step_num"] == 1
    assert step1["action_type"] == "EMAIL_1"
    assert step1["message_text"] == "Hello there!"
    assert step1["subject"] == "Hey"
    assert step1["ai_write"] == 0
    assert step1["status"] == "sent"
    assert step1["quality_score"] == 85

    step2 = rows[1]
    assert step2["step_num"] == 2
    assert step2["action_type"] == "LINKEDIN_DM"
    assert step2["ai_write"] == 1
    assert step2["status"] == "pending"


def test_list_outreach_steps_filtered_by_workflow(temp_db, campaign_id):
    """Should be able to filter steps by workflow_id."""
    steps_wf1 = [{"step_num": 1, "action_type": "EMAIL_1", "channel": "email"}]
    steps_wf2 = [{"step_num": 1, "action_type": "LINKEDIN_DM", "channel": "linkedin_dm"}]

    temp_db.save_outreach_steps(campaign_id, "wf_a", thread_id="t1", steps=steps_wf1)
    temp_db.save_outreach_steps(campaign_id, "wf_b", thread_id="t2", steps=steps_wf2)

    rows_a = temp_db.list_outreach_steps(campaign_id, workflow_id="wf_a")
    assert len(rows_a) == 1
    assert rows_a[0]["action_type"] == "EMAIL_1"

    rows_b = temp_db.list_outreach_steps(campaign_id, workflow_id="wf_b")
    assert len(rows_b) == 1
    assert rows_b[0]["action_type"] == "LINKEDIN_DM"


def test_update_outreach_step_status(temp_db, campaign_id):
    """Updating a step's status should persist."""
    workflow_id = "wf_update"
    steps = [{"step_num": 1, "action_type": "EMAIL_1", "channel": "email", "status": "pending"}]
    temp_db.save_outreach_steps(campaign_id, workflow_id, thread_id="t", steps=steps)

    temp_db.update_outreach_step_status(
        campaign_id, workflow_id, step_num=1,
        status="sent",
        message_text="Updated message",
        quality_score=92,
        sent_at="2025-01-01T00:00:00Z",
    )

    rows = temp_db.list_outreach_steps(campaign_id, workflow_id=workflow_id)
    assert rows[0]["status"] == "sent"
    assert rows[0]["message_text"] == "Updated message"
    assert rows[0]["quality_score"] == 92
    assert rows[0]["sent_at"] == "2025-01-01T00:00:00Z"


def test_save_outreach_steps_with_string_message():
    """If message is a plain string (not a dict), it should still be persisted."""
    from app.store import CampaignStore
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    store = CampaignStore(db_path=path)
    cid = store.create_campaign(
        user_id="test", raw_icp="icp", user_offering="offering",
    )
    steps = [{
        "step_num": 1,
        "action_type": "LINKEDIN_CONNECT",
        "channel": "linkedin_dm",
        "message": "Connection request note",
        "ai_write": False,
    }]
    store.save_outreach_steps(cid, "wf_str", thread_id="t", steps=steps)
    rows = store.list_outreach_steps(cid)
    assert rows[0]["message_text"] == "Connection request note"
    os.remove(path)


def test_save_outreach_steps_handles_none_message():
    """None message should result in null message_text."""
    from app.store import CampaignStore
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    store = CampaignStore(db_path=path)
    cid = store.create_campaign(
        user_id="test", raw_icp="icp", user_offering="offering",
    )
    steps = [{
        "step_num": 1,
        "action_type": "LINKEDIN_CONNECT",
        "channel": "linkedin_dm",
        "message": None,
        "ai_write": False,
    }]
    store.save_outreach_steps(cid, "wf_none", thread_id="t", steps=steps)
    rows = store.list_outreach_steps(cid)
    assert rows[0]["message_text"] is None
    os.remove(path)


# ── CustomOutreachRequest payload tests ───────────────────────────────

def test_custom_outreach_request_minimal():
    """Minimal valid custom outreach request should build correctly."""
    from app.api import CustomOutreachRequest, CustomSequenceStep
    req = CustomOutreachRequest(
        company_name="TestCo",
        steps=[
            CustomSequenceStep(
                step_num=1,
                action_type="EMAIL_1",
                channel="email",
                message="Hello world",
            )
        ],
    )
    assert req.company_name == "TestCo"
    assert req.sender_company == "My Company"
    assert req.use_native_language is False
    assert len(req.steps) == 1
    assert req.persona == {}


def test_custom_outreach_request_with_persona():
    """Persona data should be captured."""
    from app.api import CustomOutreachRequest, CustomSequenceStep
    req = CustomOutreachRequest(
        company_name="ProspectCo",
        persona={"full_name": "Jane Doe", "email": "jane@test.com"},
        steps=[
            CustomSequenceStep(
                step_num=1,
                action_type="EMAIL_1",
                channel="email",
                message="Hey Jane",
            )
        ],
    )
    assert req.persona["full_name"] == "Jane Doe"
    assert req.persona["email"] == "jane@test.com"


def test_custom_outreach_request_rejects_empty_steps():
    """Must have at least one step."""
    from app.api import CustomOutreachRequest
    from pydantic import ValidationError
    with pytest.raises(ValidationError):
        CustomOutreachRequest(
            company_name="TestCo",
            steps=[],
        )


def test_mixed_ai_write_steps():
    """Mix of ai_write=True and ai_write=False should be valid."""
    from app.api import CustomSequenceStep
    human_step = CustomSequenceStep(
        step_num=1,
        action_type="EMAIL_1",
        channel="email",
        message="Hand-written intro",
        ai_write=False,
    )
    ai_step = CustomSequenceStep(
        step_num=2,
        action_type="LINKEDIN_DM",
        channel="linkedin_dm",
        message="",
        ai_write=True,
    )
    assert human_step.ai_write is False
    assert human_step.message == "Hand-written intro"
    assert ai_step.ai_write is True
    assert ai_step.message == ""
