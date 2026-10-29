from __future__ import annotations

import pytest

from app.pipeline.outreach import (
    build_outreach_payload,
    normalize_research_signals,
)


def _sample_package():
    return {
        "lead_id": "camp-1:persona-1",
        "campaign_id": "camp-1",
        "icp": {
            "raw": "ICP text",
            "features": {},
            "user_offering": "Cyber analytics",
        },
        "company": {
            "apollo_id": "co-1",
            "name": "Acme Inc",
            "domain": "acme.com",
            "country": "France",
            "city": "Paris",
            "intent_signals": {
                "job_offers": [{"title": "Senior SDR"}],
                "news": [{"headline": "Raised Series B"}],
            },
            "intent_summary": "Hiring sales; just raised funding",
        },
        "persona": {
            "apollo_id": "persona-1",
            "name": "Alice Martin",
            "title": "VP Sales",
            "email": "alice@acme.com",
            "phone": "+33 1 23 45 67 89",
            "is_linkedin_connected": True,
            "signals": "Posted about scaling SDRs",
        },
    }


def _sample_campaign():
    return {
        "raw_icp": "ICP text",
        "user_offering": "Cyber analytics",
        "outreach_config": {
            "sender_company": "NudgeShield",
            "sender_elevator_pitch": "We protect insurers",
            "offer_name": "Risk Audit",
            "solution_summary": "Quick risk snapshot",
            "cta": "Reply to book a call",
            "approval_mode": "per_step",
            "use_native_language": True,
            "message_language": "fr",
            "has_inmail_credits": True,
            "debug_mode": False,
        },
    }


def test_normalize_string_signal():
    pkg = _sample_package()
    signals = normalize_research_signals(pkg)
    assert any(s["type"] == "persona_signal" and "scaling SDRs" in s["content"] for s in signals)


def test_normalize_list_of_dict_signals():
    pkg = _sample_package()
    pkg["persona"]["signals"] = [
        {"type": "post", "content": "hiring", "why_relevant": "relevant"},
        {"summary": "budget news"},
    ]
    signals = normalize_research_signals(pkg)
    assert any(s["type"] == "post" for s in signals)
    assert any("budget news" in s["content"] for s in signals)


def test_normalize_company_intent_signals():
    pkg = _sample_package()
    signals = normalize_research_signals(pkg)
    assert any(s["type"] == "job_offer" and "Senior SDR" in s["content"] for s in signals)
    assert any(s["type"] == "news" and "Raised Series B" in s["content"] for s in signals)
    assert any(s["type"] == "company_intent" for s in signals)


def test_build_outreach_payload_keys():
    pkg = _sample_package()
    campaign = _sample_campaign()
    payload = build_outreach_payload(pkg, campaign)

    assert payload["lead_id"] == "camp-1:persona-1"
    assert payload["campaign_id"] == "camp-1"
    assert payload["entreprise"] == "Acme Inc"
    assert payload["contact_full_name"] == "Alice Martin"
    assert payload["contact_job_title"] == "VP Sales"
    assert payload["contact_email"] == "alice@acme.com"
    assert payload["contact_country"] == "France"
    assert payload["contact_city"] == "Paris"
    assert payload["contact_linkedin"] == ""
    assert payload["is_connected_on_linkedin"] is True
    assert payload["has_inmail_credits"] is True
    assert payload["use_native_language"] is True
    assert payload["message_language"] == "fr"
    assert payload["approval_mode"] == "per_step"
    assert payload["sender_company"] == "NudgeShield"
    assert payload["sender_elevator_pitch"] == "We protect insurers"
    assert payload["offer_name"] == "Risk Audit"
    assert payload["solution_summary"] == "Quick risk snapshot"
    assert payload["cta"] == "Reply to book a call"
    assert payload["debug_mode"] is False
    assert isinstance(payload["research_signals"], list)
    assert len(payload["research_signals"]) > 0


def test_build_outreach_payload_solution_summary_fallback():
    pkg = _sample_package()
    campaign = _sample_campaign()
    campaign["outreach_config"]["solution_summary"] = ""
    payload = build_outreach_payload(pkg, campaign)
    # Falls back to campaign user_offering
    assert payload["solution_summary"] == "Cyber analytics"


def test_build_outreach_payload_env_defaults_when_no_campaign_config():
    pkg = _sample_package()
    campaign = {"raw_icp": "ICP", "user_offering": "Cyber analytics"}
    payload = build_outreach_payload(pkg, campaign)
    # Defaults from settings
    assert "sender_company" in payload
    assert "offer_name" in payload
    assert payload["solution_summary"] == "Cyber analytics"
    assert payload["approval_mode"] == "per_sequence"


def test_build_outreach_payload_overrides_win():
    pkg = _sample_package()
    campaign = _sample_campaign()
    overrides = {"offer_name": "Override Offer", "debug_mode": True}
    payload = build_outreach_payload(pkg, campaign, overrides)
    assert payload["offer_name"] == "Override Offer"
    assert payload["debug_mode"] is True


def test_web_profil_brut_coerces_dict_signals():
    """persona['signals'] as a dict must not crash web_profil_brut slicing."""
    pkg = _sample_package()
    pkg["persona"]["signals"] = {"intent": "hiring", "budget": "high"}
    campaign = _sample_campaign()
    payload = build_outreach_payload(pkg, campaign)
    assert isinstance(payload["web_profil_brut"], str)
    assert "hiring" in payload["web_profil_brut"]


def test_web_profil_brut_coerces_list_signals():
    """persona['signals'] as a list must produce a string web_profil_brut."""
    pkg = _sample_package()
    pkg["persona"]["signals"] = ["posted about SDR scaling", "hiring"]
    campaign = _sample_campaign()
    payload = build_outreach_payload(pkg, campaign)
    assert isinstance(payload["web_profil_brut"], str)
    assert "SDR scaling" in payload["web_profil_brut"]


def test_web_profil_brut_truncates_long_string():
    """A very long signals string is truncated to 2000 chars."""
    pkg = _sample_package()
    pkg["persona"]["signals"] = "x" * 5000
    campaign = _sample_campaign()
    payload = build_outreach_payload(pkg, campaign)
    assert isinstance(payload["web_profil_brut"], str)
    assert len(payload["web_profil_brut"]) == 2000


def test_web_profil_brut_falls_back_to_public_signals():
    """When signals is missing/None, public_signals is used."""
    pkg = _sample_package()
    pkg["persona"]["signals"] = None
    pkg["persona"]["public_signals"] = "Posted about scaling SDRs"
    campaign = _sample_campaign()
    payload = build_outreach_payload(pkg, campaign)
    assert payload["web_profil_brut"] == "Posted about scaling SDRs"
