from __future__ import annotations

import pytest

from app.api import _outreach_config_from_params
from app.pipeline.outreach import build_outreach_payload


# ── Sample test fixtures ────────────────────────────────────────────────────

def _sample_package():
    return {
        "lead_id": "camp-1:persona-1",
        "campaign_id": "camp-1",
        "icp": {"raw": "ICP text", "features": {}, "user_offering": "Cyber analytics"},
        "company": {
            "apollo_id": "co-1",
            "name": "Acme Inc",
            "domain": "acme.com",
            "country": "France",
            "city": "Paris",
            "intent_signals": {},
            "intent_summary": "",
        },
        "persona": {
            "apollo_id": "persona-1",
            "name": "Alice Martin",
            "title": "VP Sales",
            "email": "alice@acme.com",
            "signals": "Posted about scaling",
        },
    }


def _sample_campaign(**extra_outreach_config):
    outreach_config = {
        "sender_company": "NudgeShield",
        "offer_name": "Risk Audit",
        "solution_summary": "Quick snapshot",
        "cta": "Reply to book",
    }
    outreach_config.update(extra_outreach_config)
    return {
        "raw_icp": "ICP text",
        "user_offering": "Cyber analytics",
        "outreach_config": outreach_config,
    }


# ── _outreach_config_from_params tests ─────────────────────────────────────

def _make_body(**extra):
    """Build a minimal params dict that _outreach_config_from_params accepts.

    _outreach_config_from_params reads keys via dict.get(), so a plain dict
    (the shape saved by POST /campaigns/params) is the correct input.
    """
    defaults = {
        "auto_start_outreach": False,
        "sender_company": "TestCo",
        "sender_elevator_pitch": "",
        "offer_name": "Test Offer",
        "solution_summary": "",
        "cta": "",
        "approval_mode": "per_sequence",
        "use_native_language": False,
        "message_language": None,
        "has_inmail_credits": False,
        "debug_mode": True,
        # New fields — None by default
        "max_touches": None,
        "max_days": None,
        "preferred_first_channel": None,
        "sequence_options": None,
        "stage_instructions": None,
        "personality_config": None,
    }
    defaults.update(extra)
    return defaults


class TestOutreachConfigFromParams:

    def test_all_existing_fields_are_captured(self):
        body = _make_body()
        cfg = _outreach_config_from_params(body)
        assert cfg["auto_start_outreach"] is False
        assert cfg["sender_company"] == "TestCo"
        assert cfg["offer_name"] == "Test Offer"
        assert cfg["approval_mode"] == "per_sequence"

    def test_new_fields_are_none_by_default(self):
        body = _make_body()
        cfg = _outreach_config_from_params(body)
        assert cfg["max_touches"] is None
        assert cfg["max_days"] is None
        assert cfg["preferred_first_channel"] is None
        assert cfg["sequence_options"] is None
        assert cfg["stage_instructions"] is None
        assert cfg["personality_config"] is None

    def test_personality_config_captured_when_populated(self):
        body = _make_body(personality_config={
            "base_template": "consultative",
            "personality_traits": ["concise", "warm"],
            "urgency_level": "low",
        })
        cfg = _outreach_config_from_params(body)
        assert cfg["personality_config"] == {
            "base_template": "consultative",
            "personality_traits": ["concise", "warm"],
            "urgency_level": "low",
        }

    def test_sequence_options_captured_when_populated(self):
        body = _make_body(sequence_options={
            "vary_tone": True,
            "include_breakup": False,
        })
        cfg = _outreach_config_from_params(body)
        assert cfg["sequence_options"] == {"vary_tone": True, "include_breakup": False}

    def test_stage_instructions_captured_when_populated(self):
        body = _make_body(stage_instructions={
            "first_touch": "DORA pain point",
            "second_touch": "Series B + product",
        })
        cfg = _outreach_config_from_params(body)
        assert cfg["stage_instructions"] == {
            "first_touch": "DORA pain point",
            "second_touch": "Series B + product",
        }

    def test_max_touches_and_max_days_captured(self):
        body = _make_body(max_touches=4, max_days=10)
        cfg = _outreach_config_from_params(body)
        assert cfg["max_touches"] == 4
        assert cfg["max_days"] == 10

    def test_preferred_first_channel_captured(self):
        body = _make_body(preferred_first_channel="linkedin_dm")
        cfg = _outreach_config_from_params(body)
        assert cfg["preferred_first_channel"] == "linkedin_dm"

    def test_all_six_new_fields_captured_together(self):
        """End-to-end: all 6 new fields captured in one call."""
        body = _make_body(
            max_touches=5,
            max_days=14,
            preferred_first_channel="email",
            sequence_options={"vary_tone": True, "cross_channel": True},
            stage_instructions={
                "first_touch": "Lead with pain point",
                "third_touch": "Close with CTA",
            },
            personality_config={
                "base_template": "consultative",
                "never_use_phrases": ["disrupt", "game-changer"],
                "voice_samples": ["Hi, saw your post..."],
            },
        )
        cfg = _outreach_config_from_params(body)

        assert cfg["max_touches"] == 5
        assert cfg["max_days"] == 14
        assert cfg["preferred_first_channel"] == "email"
        assert cfg["sequence_options"] == {"vary_tone": True, "cross_channel": True}
        assert cfg["stage_instructions"] == {
            "first_touch": "Lead with pain point",
            "third_touch": "Close with CTA",
        }
        assert cfg["personality_config"]["base_template"] == "consultative"
        assert "disrupt" in cfg["personality_config"]["never_use_phrases"]
        assert len(cfg["personality_config"]["voice_samples"]) == 1


# ── build_outreach_payload tests ─────────────────────────────────────────────

class TestBuildOutreachPayloadNewFields:

    def test_personality_config_forwarded_from_outreach_config(self):
        pkg = _sample_package()
        campaign = _sample_campaign(personality_config={
            "base_template": "consultative",
            "urgency_level": "low",
            "humor_sarcasm": False,
        })
        payload = build_outreach_payload(pkg, campaign)
        assert "personality_config" in payload
        assert payload["personality_config"]["base_template"] == "consultative"
        assert payload["personality_config"]["urgency_level"] == "low"

    def test_personality_config_forwarded_with_voice_samples(self):
        pkg = _sample_package()
        campaign = _sample_campaign(personality_config={
            "voice_samples": ["Hi Alice — saw your post about SDR scaling..."],
            "never_use_phrases": ["disrupt", "revolutionize"],
        })
        payload = build_outreach_payload(pkg, campaign)
        assert payload["personality_config"]["voice_samples"] == [
            "Hi Alice — saw your post about SDR scaling...",
        ]
        assert "disrupt" in payload["personality_config"]["never_use_phrases"]

    def test_sequence_options_forwarded(self):
        pkg = _sample_package()
        campaign = _sample_campaign(sequence_options={
            "vary_tone": True,
            "include_breakup": True,
            "reference_previous": False,
            "escalate_urgency": True,
            "cross_channel": False,
        })
        payload = build_outreach_payload(pkg, campaign)
        assert payload["sequence_options"] == {
            "vary_tone": True,
            "include_breakup": True,
            "reference_previous": False,
            "escalate_urgency": True,
            "cross_channel": False,
        }

    def test_stage_instructions_forwarded(self):
        pkg = _sample_package()
        campaign = _sample_campaign(stage_instructions={
            "first_touch": "Lead with DORA",
            "second_touch": "Reference Series B",
        })
        payload = build_outreach_payload(pkg, campaign)
        assert payload["stage_instructions"] == {
            "first_touch": "Lead with DORA",
            "second_touch": "Reference Series B",
        }

    def test_max_touches_and_max_days_forwarded(self):
        pkg = _sample_package()
        campaign = _sample_campaign(max_touches=3, max_days=7)
        payload = build_outreach_payload(pkg, campaign)
        assert payload["max_touches"] == 3
        assert payload["max_days"] == 7

    def test_preferred_first_channel_forwarded(self):
        pkg = _sample_package()
        campaign = _sample_campaign(preferred_first_channel="email")
        payload = build_outreach_payload(pkg, campaign)
        assert payload["preferred_first_channel"] == "email"

    def test_none_fields_are_skipped_in_payload(self):
        """When config values are None, they should NOT appear in payload."""
        pkg = _sample_package()
        campaign = _sample_campaign(
            personality_config=None,
            sequence_options=None,
            stage_instructions=None,
            max_touches=None,
            max_days=None,
            preferred_first_channel=None,
        )
        payload = build_outreach_payload(pkg, campaign)
        # None values should not be in payload
        assert "personality_config" not in payload
        assert "sequence_options" not in payload
        assert "stage_instructions" not in payload
        assert "max_touches" not in payload
        assert "max_days" not in payload
        assert "preferred_first_channel" not in payload

    def test_overrides_win_over_outreach_config(self):
        """When overrides provide new fields, they win over outreach_config."""
        pkg = _sample_package()
        campaign = _sample_campaign(
            personality_config={"base_template": "campaign_level"},
            max_touches=4,
        )
        overrides = {
            "personality_config": {"base_template": "override_level"},
            "max_touches": 7,
            "stage_instructions": {"first_touch": "override instruction"},
        }
        payload = build_outreach_payload(pkg, campaign, overrides)
        assert payload["personality_config"]["base_template"] == "override_level"
        assert payload["max_touches"] == 7
        assert payload["stage_instructions"] == {"first_touch": "override instruction"}

    def test_all_six_new_fields_forwarded_together(self):
        """End-to-end: all 6 new fields arrive in the MCP payload."""
        pkg = _sample_package()
        campaign = _sample_campaign(
            max_touches=5,
            max_days=12,
            preferred_first_channel="linkedin_dm",
            sequence_options={"vary_tone": True, "cross_channel": True},
            stage_instructions={
                "first_touch": "DORA pain point",
                "second_touch": "Series B",
                "third_touch": "EUR 2M + CTA",
            },
            personality_config={
                "base_template": "consultative_ciso",
                "personality_traits": ["concise", "credible", "warm", "DORA-literate"],
                "always_include_phrases": ["happy to share a case study"],
                "never_use_phrases": ["disrupt", "game-changer"],
                "urgency_level": "low",
                "humor_sarcasm": False,
                "voice_samples": [
                    "Hi Alice — saw your post about scaling SDRs...",
                    "Quick follow-up on the growth metrics",
                ],
            },
        )
        payload = build_outreach_payload(pkg, campaign)

        # All 6 must be present
        assert payload["max_touches"] == 5
        assert payload["max_days"] == 12
        assert payload["preferred_first_channel"] == "linkedin_dm"
        assert payload["sequence_options"]["vary_tone"] is True
        assert payload["sequence_options"]["cross_channel"] is True
        assert payload["stage_instructions"]["first_touch"] == "DORA pain point"
        assert payload["stage_instructions"]["third_touch"] == "EUR 2M + CTA"
        assert payload["personality_config"]["base_template"] == "consultative_ciso"
        assert len(payload["personality_config"]["voice_samples"]) == 2
        assert "disrupt" in payload["personality_config"]["never_use_phrases"]

    def test_payload_still_has_existing_fields(self):
        """New fields must not break existing payload structure."""
        pkg = _sample_package()
        campaign = _sample_campaign(
            max_touches=4,
            personality_config={"base_template": "test"},
        )
        payload = build_outreach_payload(pkg, campaign)
        # Existing fields still present
        assert payload["lead_id"] == "camp-1:persona-1"
        assert payload["entreprise"] == "Acme Inc"
        assert payload["contact_full_name"] == "Alice Martin"
        assert payload["sender_company"] == "NudgeShield"
        # New fields present
        assert payload["max_touches"] == 4
        assert payload["personality_config"]["base_template"] == "test"
