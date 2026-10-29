"""
tests/verify_mcp_output.py
───────────────────────────
Prints the full raw JSON output from each MCP tool call for manual inspection.

Use this to verify:
  1. ICP filters are correctly extracted from the brief
  2. Company scores and breakdowns are correct
  3. Disqualification reasons are accurate
  4. Persona scores match expected values
  5. Status transitions hit the DB correctly

Run from project root:
    python qualifier_agent/tests/verify_mcp_output.py
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import sys

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

logging.basicConfig(level=logging.WARNING)  # suppress pipeline logs for clean output

from fastmcp import Client

SERVER_PATH = os.path.join(ROOT_DIR, "qualifier_mcp", "run.py")

ICP_DESCRIPTION = """
We are targeting mid-size insurance companies and fintech firms in France,
specifically in Paris (including suburbs like Nanterre, La Défense) and Lyon.

Must have:
- Industry: Insurance, Fintech, Assurance, Financial Services
- Company size: 500 to 20000 employees
- Located in: France (Paris, Lyon, Nanterre, La Défense)

Nice to have:
- Revenue range: 100M to 50B EUR
- Tech stack: Salesforce, SAP, Microsoft Teams, Python, Power BI

Exclude:
- Industries: Food & Beverage, Logistics, Retail, Wholesale
- Keywords: foodservice, wholesale distribution, horeca
- Company size: 1 to 10 employees

Target roles:
- Chief Revenue Officer
- VP Sales
- Head of Sales
- Sales Director
- Commercial Director
"""

USER_OFFERING = """
LeadPulse is a B2B outbound sales automation platform that helps sales teams
identify, qualify, and engage high-intent prospects using AI-driven scoring.
"""

SOURCER_COMPANIES = [
    {
        "apollo_id":               "556936c873696421ab590d00",
        "name":                    "AXA (Entité Nanterre)",
        "domain":                  "axa.fr",
        "website_url":             "https://www.axa.fr",
        "industry":                "Assurance et Services Financiers",
        "estimated_num_employees": 9000,
        "annual_revenue":          31644000000,
        "founded_year":            1971,
        "city":                    "Nanterre",
        "country":                 "France",
        "state":                   "Ile-de-France",
        "latest_funding_stage":    "Publicly Traded",
        "is_subsidiary":           True,
        "parent_company":          "AXA Group",
        "full_description":        "AXA is a leading insurance company investing heavily in CRM modernization.",
        "short_description":       "Leading French insurer",
        "linkedin_url":            "https://www.linkedin.com/company/axa-france",
        "data_quality_score":      0.94,
        "technologies": json.dumps([
            {"uid": "salesforce", "name": "Salesforce CRM Analytics", "category": "CRM"},
            {"uid": "sap",        "name": "SAP",                       "category": "ERP"},
            {"uid": "python",     "name": "Python",                    "category": "Programming"},
        ]),
        "keywords":         json.dumps(["insurance", "assurance", "CRM", "B2B"]),
        "funding_events":   json.dumps([]),
        "competitors":      json.dumps(["Allianz France"]),
        "departments":      json.dumps({"sales": 423}),
        "suborganizations": json.dumps([]),
        "intent_signals": {
            "job_offers": [
                {
                    "title":       "Sales Development Representative",
                    "posted_date": "2026-05-15",
                    "description": "Looking for SDRs to scale our outbound B2B sales motion.",
                }
            ],
            "news": [
                {
                    "headline":       "AXA France announces €200M digital transformation investment",
                    "published_date": "2026-03-10",
                    "summary":        "AXA France is investing in digitalizing its sales processes.",
                }
            ],
        },
    },
    {
        "apollo_id":               "covea_lyon_001",
        "name":                    "Covea Lyon",
        "domain":                  "covea.fr",
        "website_url":             "https://www.covea.fr",
        "industry":                "Insurance",
        "estimated_num_employees": 2800,
        "annual_revenue":          3500000000,
        "founded_year":            2003,
        "city":                    "Lyon",
        "country":                 "France",
        "state":                   "Auvergne-Rhône-Alpes",
        "latest_funding_stage":    "Private",
        "is_subsidiary":           False,
        "parent_company":          None,
        "full_description":        "Covea Lyon is a regional mutual insurance group.",
        "short_description":       "Regional French insurer",
        "linkedin_url":            "https://www.linkedin.com/company/covea",
        "data_quality_score":      0.87,
        "technologies": json.dumps([
            {"uid": "sap",      "name": "SAP",             "category": "ERP"},
            {"uid": "ms_teams", "name": "Microsoft Teams", "category": "Collaboration"},
        ]),
        "keywords":         json.dumps(["insurance", "assurance", "B2B"]),
        "funding_events":   json.dumps([]),
        "competitors":      json.dumps(["MAIF"]),
        "departments":      json.dumps({"sales": 180}),
        "suborganizations": json.dumps([]),
        "intent_signals":   {"job_offers": [], "news": []},
    },
    {
        "apollo_id":               "microassur_001",
        "name":                    "MicroAssur",
        "domain":                  "microassur.fr",
        "website_url":             "https://www.microassur.fr",
        "industry":                "Insurance",
        "estimated_num_employees": 49,
        "annual_revenue":          4200000,
        "founded_year":            2019,
        "city":                    "Paris",
        "country":                 "France",
        "state":                   "Ile-de-France",
        "latest_funding_stage":    "Seed",
        "is_subsidiary":           False,
        "parent_company":          None,
        "full_description":        "MicroAssur is a Paris-based insurtech startup.",
        "short_description":       "Insurtech startup",
        "linkedin_url":            None,
        "data_quality_score":      0.78,
        "technologies":            json.dumps([]),
        "keywords":                json.dumps(["insurtech"]),
        "funding_events":          json.dumps([]),
        "competitors":             json.dumps([]),
        "departments":             json.dumps({}),
        "suborganizations":        json.dumps([]),
        "intent_signals":          {"job_offers": [], "news": []},
    },
]

SOURCER_PERSONAS = {
    "556936c873696421ab590d00": [
        {
            "name":                  "Marie Dupont",
            "title":                 "VP Sales France",
            "seniority":             "VP",
            "department":            "Sales",
            "months_in_role":        18,
            "is_linkedin_connected": True,
            "email":                 "m.dupont@axa.fr",
            "phone_number":          "+33 6 12 34 56 78",
            "public_signals":        "Recently posted about scaling outbound sales teams.",
        },
    ],
    "covea_lyon_001": [
        {
            "name":                  "Isabelle Moreau",
            "title":                 "Directrice Commerciale",
            "seniority":             "Director",
            "department":            "Sales",
            "months_in_role":        36,
            "is_linkedin_connected": True,
            "email":                 "i.moreau@covea.fr",
            "phone_number":          "+33 4 72 00 11 22",
            "public_signals":        "Long-tenured sales director.",
        },
    ],
}


def section(title: str):
    print("\n" + "═" * 70)
    print(f"  {title}")
    print("═" * 70)


def pretty(data: dict):
    print(json.dumps(data, indent=2, default=str))


async def verify():
    async with Client(SERVER_PATH) as client:

        # ── TOOL 1: start_campaign ─────────────────────────────────────────
        section("TOOL 1 — start_campaign (full raw output)")
        result = await client.call_tool("start_campaign", {
            "user_id":              "verify-user-001",
            "icp_description_text": ICP_DESCRIPTION,
            "user_offering":        USER_OFFERING,
            "blacklist":            {"companies": [], "personas": []},
            "configurable_weights": {},
        })
        output1 = json.loads(result.content[0].text)
        pretty(output1)
        campaign_id = output1["campaign_id"]

        # What to check:
        print("\n  ── VERIFY ──")
        print(f"  campaign_id present:          {'✓' if campaign_id else '✗'}")
        print(f"  status = 'running':           {'✓' if output1['status'] == 'running' else '✗'} ({output1['status']})")
        print(f"  error is None:                {'✓' if output1.get('error') is None else '✗'}")
        icp = output1.get("icp_filters", {})
        print(f"  industries extracted:         {'✓' if icp.get('industries') else '✗'} {icp.get('industries')}")
        print(f"  target_countries extracted:   {'✓' if icp.get('target_countries') else '✗'} {icp.get('target_countries')}")
        size = icp.get("company_size", {})
        print(f"  company_size.min = 500:       {'✓' if size.get('min') == 500.0 else '✗'} ({size.get('min')})")
        print(f"  company_size.max = 20000:     {'✓' if size.get('max') == 20000.0 else '✗'} ({size.get('max')})")

        # ── TOOL 4: get_campaign_status (Phase 1) ─────────────────────────
        section("TOOL 4 — get_campaign_status after Phase 1 (full raw output)")
        result = await client.call_tool("get_campaign_status", {"campaign_id": campaign_id})
        output4a = json.loads(result.content[0].text)
        pretty(output4a)

        print("\n  ── VERIFY ──")
        print(f"  status = 'running':           {'✓' if output4a['status'] == 'running' else '✗'} ({output4a['status']})")
        print(f"  user_id correct:              {'✓' if output4a['user_id'] == 'verify-user-001' else '✗'}")
        print(f"  ranked_companies is None:     {'✓' if output4a.get('ranked_companies') is None else '✗'}")

        # ── TOOL 2: resume_with_companies ─────────────────────────────────
        section("TOOL 2 — resume_with_companies (full raw output)")
        result = await client.call_tool("resume_with_companies", {
            "campaign_id":       campaign_id,
            "sourced_companies": SOURCER_COMPANIES,
        })
        output2 = json.loads(result.content[0].text)
        pretty(output2)

        print("\n  ── VERIFY ──")
        print(f"  status = 'awaiting_approval': {'✓' if output2['status'] == 'awaiting_approval' else '✗'} ({output2['status']})")
        print(f"  error is None:                {'✓' if output2.get('error') is None else '✗'}")
        ranked = output2.get("ranked_companies", [])
        print(f"  ranked_companies count = 2:   {'✓' if len(ranked) == 2 else '✗'} ({len(ranked)})")
        print(f"  MicroAssur gated out:         {'✓' if output2.get('disqualification_summary', {}).get('MUST_HAVE_SIZE_MISS') == 1 else '✗'}")

        if ranked:
            axa = next((c for c in ranked if "AXA" in c.get("name", "")), None)
            if axa:
                m = axa.get("qualification_metrics") or {}
                print(f"\n  AXA scores:")
                print(f"    tier = A:                   {'✓' if m.get('tier') == 'A' else '✗'} ({m.get('tier')})")
                print(f"    firmographic_score = 100:   {'✓' if m.get('firmographic_score') == 100.0 else '✗'} ({m.get('firmographic_score')})")
                print(f"    intent_score >= 70:         {'✓' if (m.get('intent_score') or 0) >= 70 else '✗'} ({m.get('intent_score')})")
                breakdown = m.get("breakdown", {})
                print(f"    industry_match = exact:     {'✓' if breakdown.get('industry_match', {}).get('match_quality') == 'exact' else '✗'}")
                print(f"    size_match = exact:         {'✓' if breakdown.get('size_match', {}).get('match_quality') == 'exact' else '✗'}")

        # ── TOOL 5: get_pending_campaigns ─────────────────────────────────
        section("TOOL 5 — get_pending_campaigns (full raw output)")
        result = await client.call_tool("get_pending_campaigns", {"user_id": "verify-user-001"})
        output5 = json.loads(result.content[0].text)
        pretty(output5)

        print("\n  ── VERIFY ──")
        print(f"  total_pending >= 1:           {'✓' if output5['total_pending'] >= 1 else '✗'} ({output5['total_pending']})")
        pending = output5.get("pending_campaigns", [])
        if pending:
            p = pending[0]
            print(f"  campaign_id matches:          {'✓' if p['campaign_id'] == campaign_id else '✗'}")
            print(f"  status = awaiting_approval:   {'✓' if p['status'] == 'awaiting_approval' else '✗'}")
            print(f"  ranked_companies count = 2:   {'✓' if len(p.get('ranked_companies', [])) == 2 else '✗'} ({len(p.get('ranked_companies', []))})")

        # ── TOOL 3: resume_with_approvals ─────────────────────────────────
        section("TOOL 3 — resume_with_approvals (full raw output)")
        result = await client.call_tool("resume_with_approvals", {
            "campaign_id":                 campaign_id,
            "approved_apollo_ids":         ["556936c873696421ab590d00", "covea_lyon_001"],
            "sourced_personas_by_company": SOURCER_PERSONAS,
        })
        output3 = json.loads(result.content[0].text)
        pretty(output3)

        print("\n  ── VERIFY ──")
        print(f"  status = 'completed':         {'✓' if output3['status'] == 'completed' else '✗'} ({output3['status']})")
        print(f"  error is None:                {'✓' if output3.get('error') is None else '✗'}")
        personas = output3.get("ranked_personas", [])
        print(f"  total_personas_ranked = 2:    {'✓' if output3['total_personas_ranked'] == 2 else '✗'} ({output3['total_personas_ranked']})")
        if personas:
            marie = next((p for p in personas if "Marie" in (p.get("name") or "")), None)
            isabelle = next((p for p in personas if "Isabelle" in (p.get("name") or "")), None)
            print(f"  Marie Dupont present:         {'✓' if marie else '✗'}")
            print(f"  Isabelle Moreau present:      {'✓' if isabelle else '✗'}")
            if marie:
                print(f"  Marie score >= 80:            {'✓' if (marie.get('persona_score') or 0) >= 80 else '✗'} ({marie.get('persona_score')})")
            if isabelle:
                print(f"  Isabelle score >= 80:         {'✓' if (isabelle.get('persona_score') or 0) >= 80 else '✗'} ({isabelle.get('persona_score')})")

        # ── TOOL 4: get_campaign_status (final) ───────────────────────────
        section("TOOL 4 — get_campaign_status final (full raw output)")
        result = await client.call_tool("get_campaign_status", {"campaign_id": campaign_id})
        output4b = json.loads(result.content[0].text)
        pretty(output4b)

        print("\n  ── VERIFY ──")
        print(f"  status = 'completed':         {'✓' if output4b['status'] == 'completed' else '✗'} ({output4b['status']})")
        print(f"  ranked_companies cleared:     {'✓' if output4b.get('ranked_companies') is None else '✗'}")
        print(f"  error_message is None:        {'✓' if output4b.get('error_message') is None else '✗'}")

        section("VERIFICATION COMPLETE")
        print(f"  campaign_id: {campaign_id}")
        print("  Cross-check this campaign_id in your Supabase dashboard.")
        print("  All ✓ = MCP server is returning correct results.")
        print("  Any ✗ = something to investigate in the field marked.\n")


if __name__ == "__main__":
    asyncio.run(verify())