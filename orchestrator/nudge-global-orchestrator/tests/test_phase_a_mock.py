"""Unit test for domain mapping helpers and mock Phase A."""

from __future__ import annotations

import asyncio
import json

from app.domain import (
    _extract_email_from_enrichment,
    _extract_phone_from_enrichment,
    company_size_to_employee_ranges,
    icp_filters_to_sourcer_args,
    to_qualifier_company,
)
from app.pipeline import PhaseAPipeline
from app.store import CampaignStore


def test_employee_ranges():
    ranges = company_size_to_employee_ranges({"min": 500, "max": 2000})
    assert "501,1000" in ranges
    assert "1001,5000" in ranges
    assert "1,10" not in ranges


def test_full_span_size_omits_apollo_ranges():
    """1–200000 covers every Apollo bucket; omit API filter (post-filter instead)."""
    assert company_size_to_employee_ranges({"min": 1, "max": 200000}) == []


def test_icp_filters_country_beats_continent():
    """Morocco must not expand search to Africa (Egypt, etc.)."""
    args = icp_filters_to_sourcer_args({
        "industries": ["Software"],
        "target_countries": ["Morocco"],
        "target_continents": ["Africa"],
        "company_size": {"min": 1, "max": 200000},
    })
    assert args["locations"] == ["Morocco"]
    assert args["continent"] is None
    assert args["employee_ranges"] == []
    assert args["max_employees"] == 200000


def test_icp_filters_continent_only_when_no_country():
    args = icp_filters_to_sourcer_args({
        "industries": ["Software"],
        "target_countries": [],
        "target_continents": ["Africa"],
        "company_size": None,
    })
    assert args["locations"] == []
    assert args["continent"] == "Africa"


def test_company_within_icp_size_rejects_over_max():
    from app.domain import company_within_icp_size

    size = {"min": 1, "max": 200000}
    assert company_within_icp_size({"estimated_num_employees": 150000}, size)
    assert not company_within_icp_size({"estimated_num_employees": 363000}, size)
    # Missing headcount is allowed (qualifier same contract)
    assert company_within_icp_size({"estimated_num_employees": None}, size)


def test_extract_contact_fields_from_enrichment():
    email = _extract_email_from_enrichment({
        "email": None,
        "sanitized_emails": ["derek.campbell@canadapost.ca"],
    })
    assert email == "derek.campbell@canadapost.ca"

    phone = _extract_phone_from_enrichment({
        "phone_numbers": [{"sanitized_number": "+17804927716", "raw_number": "+1 780-492-7716"}],
        "sanitized_numbers": ["+17804927716"],
    })
    assert phone == "+17804927716"


def test_to_qualifier_company():
    raw = {
        "apollo_id": "abc",
        "name": "Acme",
        "domain": "acme.com",
        "industry": "Automotive Distribution",
        "global_industry": "Finance",
        "estimated_num_employees": "10000+",
        "location": {"city": "Rzeszow", "country": "Poland"},
        "technologies": [{"name": "Salesforce"}],
        "keywords": ["b2b"],
    }
    out = to_qualifier_company(raw)
    assert out["apollo_id"] == "abc"
    assert out["estimated_num_employees"] == 10000
    assert out["industry"] == "Automotive Distribution"
    assert out["global_industry"] == "Finance"
    assert out["country"] == "Poland"
    assert out["city"] == "Rzeszow"
    assert out["intent_signals"] == {"job_offers": [], "news": []}
    assert isinstance(out["technologies"], str)


def test_to_qualifier_company_stringifies_oversized_suborg_ids():
    """Apollo sometimes emits numeric IDs wider than 64-bit; msgpack cannot store them."""
    huge_id = 674818248291510001067163
    raw = {
        "apollo_id": "54a25eaa7468692e7189f71d",
        "name": "SoFi",
        "suborganizations": [{"id": huge_id, "name": "SoFi Bank"}],
    }
    out = to_qualifier_company(raw)
    parsed = json.loads(out["suborganizations"])
    assert parsed[0]["id"] == str(huge_id)
    assert isinstance(parsed[0]["id"], str)


def test_select_best_persona_combines_company_and_persona_scores():
    from app.domain import select_best_persona

    ranked_companies = [
        {
            "apollo_id": "co-high",
            "qualification_metrics": {"total_score": 90.0},
        },
        {
            "apollo_id": "co-low",
            "qualification_metrics": {"total_score": 50.0},
        },
    ]
    personas_by_company = {
        "co-high": [{"apollo_id": "p1", "name": "Alice", "persona_score": 60}],
        "co-low": [{"apollo_id": "p2", "name": "Bob", "persona_score": 95}],
    }
    ranked_personas = [
        {"apollo_id": "p1", "name": "Alice", "persona_score": 60},
        {"apollo_id": "p2", "name": "Bob", "persona_score": 95},
    ]

    winner = select_best_persona(
        ranked_personas,
        ranked_companies,
        personas_by_company,
        company_weight=0.5,
        persona_weight=0.5,
    )
    assert winner is not None
    assert winner["apollo_id"] == "p1"
    assert winner["company_apollo_id"] == "co-high"
    assert winner["combined_lead_score"] == 75.0


def test_limit_companies_for_persona_fetch():
    from app.domain import limit_companies_for_persona_fetch

    companies = [
        {"apollo_id": "a", "qualification_metrics": {"total_score": 70}},
        {"apollo_id": "b", "qualification_metrics": {"total_score": 90}},
        {"apollo_id": "c", "qualification_metrics": {"total_score": 80}},
    ]
    limited = limit_companies_for_persona_fetch(companies, 2)
    assert [c["apollo_id"] for c in limited] == ["b", "c"]


def test_build_final_packages_company_only_when_no_personas():
    from app.domain import build_final_packages

    packages = build_final_packages(
        campaign_id="camp-1",
        qualifier_campaign_id="qual-1",
        raw_icp="icp",
        user_offering="offer",
        icp_filters={"industries": ["Software"]},
        ranked_companies=[{
            "apollo_id": "co-1",
            "name": "Acme",
            "domain": "acme.com",
            "qualification_metrics": {"total_score": 80.0},
        }],
        intent_by_apollo_id={
            "co-1": {
                "job_offers": [{"title": "Sales Rep"}],
                "news": [],
                "company_intent_summary": "hiring sales",
            }
        },
        ranked_personas=[],
        contacts={},
        personas_by_company={"co-1": []},
    )
    assert len(packages) == 1
    pkg = packages[0]
    assert pkg["company"]["apollo_id"] == "co-1"
    assert pkg["company"]["name"] == "Acme"
    assert pkg["company"]["intent_signals"]["job_offers"] == [{"title": "Sales Rep"}]
    assert pkg["company"]["intent_summary"] == "hiring sales"
    assert pkg["persona"] is None
    assert pkg["warning"] == "no personas from sourcer"


def test_mock_phase_a(tmp_path, monkeypatch):
    db = tmp_path / "t.db"
    monkeypatch.setenv("ORCHESTRATOR_MOCK", "true")
    monkeypatch.setenv("DATABASE_PATH", str(db))

    # Re-bind settings/store after env change
    from app.config import Settings
    import app.store as store_mod
    import app.pipeline as pipeline_mod
    import app.pipeline.mock_data as mock_mod

    s = Settings(orchestrator_mock=True, database_path=str(db))
    monkeypatch.setattr("app.config.settings", s)
    monkeypatch.setattr(pipeline_mod, "settings", s)
    fresh = CampaignStore(str(db))
    monkeypatch.setattr(store_mod, "store", fresh)
    monkeypatch.setattr(mock_mod, "store", fresh)

    async def _run():
        cid = fresh.create_campaign("u", "icp", "offer")
        return await PhaseAPipeline().run(
            orchestrator_campaign_id=cid,
            user_id="u",
            icp_description_text="icp",
            user_offering="offer",
        )

    result = asyncio.run(_run())
    assert result["status"] == "completed"
    assert result["package_count"] == 1
    package = result["packages"][0]
    assert package["campaign_id"] == cid
    assert package["qualifier_campaign_id"] == "mock-qualifier-1"


def test_settings_blacklist_and_weights_defaults():
    from app.config import Settings

    s = Settings(
        _env_file=None,
        blacklist_companies=["Microsoft", "Acme"],
        blacklist_personas=["https://www.linkedin.com/in/jane-doe"],
        industry_weight=0.5,
        fit_weight=0.65,
    )
    bl = s.default_blacklist()
    assert bl["companies"] == ["Microsoft", "Acme"]
    assert bl["personas"] == ["https://www.linkedin.com/in/jane-doe"]

    weights = s.default_configurable_weights()
    assert weights["industry_weight"] == 0.5
    assert weights["size_weight"] == 0.30
    assert weights["firmographic_weight"] == 0.60
    assert weights["intent_weight"] == 0.40
    assert weights["fit_weight"] == 0.65
    assert weights["reachability_weight"] == 0.20
    assert weights["primary_role_match"] == 40.0
    assert "max_km_radius" in weights
