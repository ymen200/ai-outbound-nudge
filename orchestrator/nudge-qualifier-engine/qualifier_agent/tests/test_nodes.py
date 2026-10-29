import os
import sys

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

import pytest
from unittest.mock import MagicMock, patch
from datetime import datetime

# Assuming your node is in graph/nodes.py
from graph.nodes import score_and_rank_node, _normalize_single_company, _deep_clean_placeholders
from brain.persona_ranker import _persona_intent_text
from brain.scoring import (
    evaluate_company_intent,
    calculate_funding_intent_score,
    IntentAnalysis,
)
from brain.config import FirmographicWeights


def test_persona_intent_text_prefers_neo4j_intent():
    persona = {
        "intent": "Focused on AI workflow optimization and outbound growth.",
        "public_signals": "stale signal",
        "bio": "ignored",
    }
    assert "AI workflow" in _persona_intent_text(persona)


def test_persona_intent_text_ignores_generation_failure():
    persona = {
        "intent": "Impossible de générer le résumé d'intention.",
        "public_signals": "Impossible de générer le résumé d'intention.",
    }
    assert _persona_intent_text(persona) == ""


def test_persona_intent_text_reads_raw_intent():
    persona = {
        "public_signals": "",
        "raw": {
            "intent": "Steven Weston is currently focused on leveraging AI for workflow optimization."
        },
    }
    assert "leveraging AI" in _persona_intent_text(persona)


def test_evaluate_company_intent_ignores_funding_without_sourcer_signals():
    """rank_companies path: Apollo funding alone must not trigger LLM intent."""
    llm = MagicMock()
    company = {
        "name": "Branch International",
        "intent_signals": {"job_offers": [], "news": []},
        "funding_events": [
            {"date": "2022-01-01T00:00:00.000+00:00", "type": "Debt Financing", "amount": "10M"},
            {"date": "2019-03-01T00:00:00.000+00:00", "type": "Series C", "amount": "170M"},
        ],
        "full_description": "Fintech lending in emerging markets.",
    }
    result = evaluate_company_intent(
        company,
        icp=None,
        llm=llm,
        user_offering="NudgeShield",
        firm_weights=FirmographicWeights(),
    )
    assert isinstance(result, IntentAnalysis)
    assert result.intent_score == 0.0
    llm.with_structured_output.assert_not_called()


def test_calculate_funding_intent_score_uses_stage_and_recent_events():
    company = {
        "name": "Branch International",
        "latest_funding_stage": "Series C",
        "funding_events": [
            {"date": "2022-01-01T00:00:00.000+00:00", "type": "Debt Financing", "amount": "10M"},
            {"date": "2019-03-01T00:00:00.000+00:00", "type": "Series C", "amount": "170M"},
        ],
    }
    result = calculate_funding_intent_score(company, firm_weights=FirmographicWeights())
    assert result["intent_score"] > 0
    assert "Funding-based intent" in result["intent_reasoning"]
    assert result["intent_breakdown"]["latest_funding_stage"] == "Series C"


def test_calculate_funding_intent_score_zero_without_funding_data():
    company = {"name": "No Funding Co", "funding_events": []}
    result = calculate_funding_intent_score(company, firm_weights=FirmographicWeights())
    assert result["intent_score"] == 0.0


def test_deep_clean_stringifies_ints_beyond_msgpack_range():
    huge = 674818248291510001067163
    cleaned = _deep_clean_placeholders(
        {"suborganizations": [{"id": huge, "name": "SoFi Bank"}], "ok": 42, "flag": True}
    )
    assert cleaned["suborganizations"][0]["id"] == str(huge)
    assert cleaned["ok"] == 42
    assert cleaned["flag"] is True


def test_normalize_company_stringifies_oversized_suborg_ids():
    huge = 674818248291510001067163
    raw = {
        "name": "SoFi",
        "apollo_id": "54a25eaa7468692e7189f71d",
        "suborganizations": [{"id": huge, "name": "SoFi Bank"}],
        "annual_revenue": 4769597000.0,
        "estimated_num_employees": 5000,
    }
    out = _normalize_single_company(raw)
    assert out is not None
    assert out["suborganizations"][0]["id"] == str(huge)
    assert out["annual_revenue"] == 4769597000


def _empty_disqualification_log():
    """Return a properly-typed empty DisqualificationLog dict."""
    return {
        "total_evaluated": 0,
        "total_passed": 0,
        "total_disqualified": 0,
        "records": [],
        "summary": {},
    }


@pytest.fixture
def base_state():
    """Provides a baseline mock state array matching CampaignState shape."""
    return {
        "extracted_icp": MagicMock(),
        "configurable_weights": {"industry_match": 0.4, "size_match": 0.6},
        "blacklist": {"companies": [], "personas": []},
        "pipeline_error": None,
        "campaign_id": "test-campaign",
        "sourced_companies": [
            {"name": "Alpha Corp", "industry_raw": "Software", "estimated_num_employees": 50},
            {"name": "Beta Inc", "industry_raw": "Manufacturing", "estimated_num_employees": 500},
            {"name": "Gamma LLC", "industry_raw": "Retail", "estimated_num_employees": 10},
        ],
        "disqualification_log": _empty_disqualification_log(),
    }


# ─── TEST CASE 1: PIPELINE ERROR HALTS EXECUTION ─────────────────────────────
def test_score_and_rank_node_pipeline_error():
    """Should return empty dict (no-op) when pipeline_error is set."""
    state = {
        "pipeline_error": "ICP extraction failed: timeout.",
        "extracted_icp": None,
        "sourced_companies": [{"name": "Test"}],
    }

    result = score_and_rank_node(state)

    assert result == {}


# ─── TEST CASE 2: MISSING ICP HALTS WITH ERROR ────────────────────────────────
def test_score_and_rank_node_missing_icp():
    """Should return pipeline_error when no ICP context exists."""
    state = {
        "extracted_icp": None,
        "sourced_companies": [{"name": "Test"}],
        "pipeline_error": None,
    }

    result = score_and_rank_node(state)

    assert "pipeline_error" in result
    assert "Missing extracted_icp" in result["pipeline_error"]


# ─── TEST CASE 3: FULL SCORING PATH (WITH MOCKS) ──────────────────────────────
@patch("graph.nodes._get_groq_llm")
@patch("graph.nodes._location_agent")
@patch("graph.nodes.calculate_company_score")
@patch("graph.nodes.calculate_funding_intent_score")
def test_score_and_rank_node_success_path(
    mock_funding_intent,
    mock_calculate_score,
    mock_location_agent,
    mock_get_llm,
    base_state,
):
    """
    Verifies:
      - Geo-filtering logs disqualified companies.
      - Firmographic scoring splits companies into ranked / nurture / discard buckets.
      - Funding intent only fires for companies >= passing_threshold (default 50.0).
      - Final ranked list is sorted by total_score descending.

    Node 4 returns a PARTIAL dict (LangGraph contract), not the full state.
    """

    # 1. Mock Geospatial Filter: Let Alpha and Beta pass, drop Gamma
    mock_location_agent.filter_companies.return_value = [
        {"name": "Alpha Corp"},
        {"name": "Beta Inc"},
    ]

    # 2. Mock Firmographic Scoring:
    #    Alpha Corp: 80.0 (well above passing_threshold=50.0 -> funding intent WILL run)
    #    Beta Inc:   20.0 (below passing_threshold=50.0 -> funding intent will NOT run)
    def side_effect_score(company, icp, weights, llm, firm_weights=None, callbacks=None):
        if company["name"] == "Alpha Corp":
            return {"firmographic_score": 80.0, "breakdown": {}, "normalized_weights": {}}
        return {"firmographic_score": 20.0, "breakdown": {}, "normalized_weights": {}}

    mock_calculate_score.side_effect = side_effect_score

    # 3. Mock funding intent (only called for Alpha Corp)
    mock_funding_intent.return_value = {
        "intent_score": 90,
        "intent_reasoning": "Funding-based intent from Series C.",
        "intent_breakdown": {"funding_stage_score": 78.0},
    }

    # ══════════════════════════════════════════════════════════════════════════
    # EXECUTE THE NODE — returns a partial update dict, NOT the full state
    # ══════════════════════════════════════════════════════════════════════════
    result = score_and_rank_node(base_state)

    # ══════════════════════════════════════════════════════════════════════════
    # ASSERTIONS
    # ══════════════════════════════════════════════════════════════════════════

    # A. Result is a partial dict (LangGraph contract)
    assert isinstance(result, dict)
    assert "sourced_companies" in result
    assert "ranked_companies" in result
    assert "disqualification_log" in result

    # B. Disqualification log includes geo-drop (Gamma)
    disq_log = result["disqualification_log"]
    assert disq_log["total_evaluated"] == 3  # All 3 companies evaluated
    assert disq_log["total_disqualified"] >= 1

    # C. Ranked companies: only Alpha (firm=80 >= passing_threshold=50)
    ranked = result["ranked_companies"]
    assert len(ranked) == 1
    assert ranked[0]["name"] == "Alpha Corp"

    # D. Alpha Corp Metrics (firm=80 >= passing_threshold -> funding intent evaluated)
    alpha_metrics = ranked[0]["qualification_metrics"]
    assert alpha_metrics["firmographic_score"] == 80.0
    assert alpha_metrics["intent_score"] == 90
    # Total = (80 * 0.6) + (90 * 0.4) = 48 + 36 = 84.0
    assert alpha_metrics["total_score"] == 84.0
    assert alpha_metrics["tier"] == "A"
    assert alpha_metrics["intent_reasoning"] == "Funding-based intent from Series C."

    # E. Nurture companies: Beta (firm=20, between nurture_threshold=25 and passing_threshold=50)
    nurture = result["nurture_companies"]
    assert len(nurture) == 1
    assert nurture[0]["name"] == "Beta Inc"
    assert nurture[0]["qualification_metrics"]["tier"] == "Nurture"

    # F. Verify funding intent mock call count (only called ONCE, for Alpha)
    assert mock_funding_intent.call_count == 1
