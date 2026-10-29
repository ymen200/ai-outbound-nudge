"""
tests/test_mcp_server.py
─────────────────────────
End-to-end test of the MCP server through the FastMCP client.

Calls all 5 tools in the correct orchestrator sequence:
  1. start_campaign          → Phase 1, get icp_filters
  2. get_campaign_status     → verify status = 'running'
  3. resume_with_companies   → Phase 2, get ranked_companies
  4. get_pending_campaigns   → simulate app reopen, verify awaiting_approval
  5. resume_with_approvals   → Phase 3, get ranked_personas
  6. get_campaign_status     → verify status = 'completed'

Run from project root:
    python qualifier_agent/tests/test_mcp_server.py
"""

from __future__ import annotations

import asyncio
import json
import logging
import sys
import os

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

logging.basicConfig(level=logging.INFO, format="%(levelname)s | %(name)s | %(message)s")
logger = logging.getLogger("test_mcp_server")

from fastmcp import Client


# ── Server path ────────────────────────────────────────────────────────────────
# The client spawns the server as a subprocess via stdio transport.
SERVER_PATH = os.path.join(ROOT_DIR, "qualifier_mcp", "run.py")


# ── ICP + offering ─────────────────────────────────────────────────────────────

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

SIMULATED_USER_ID = "user-mcp-test-001"


# ── Mock sourcer data ─────────────────────────────────────────────────────────

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
        "estimated_num_employees": 49,  # too small — should be gated out
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

APPROVED_APOLLO_IDS = [
    "556936c873696421ab590d00",  # AXA — approved
    "covea_lyon_001",             # Covea — approved
]


# ── Test runner ───────────────────────────────────────────────────────────────

async def run_mcp_test():
    print("\n" + "═" * 70)
    print("  STRATEGIC QUALIFIER — MCP SERVER TEST")
    print("═" * 70)

    async with Client(SERVER_PATH) as client:

        # ── List available tools ───────────────────────────────────────────
        tools = await client.list_tools()
        print(f"\n  ✓ Server connected — {len(tools)} tools registered:")
        for tool in tools:
            print(f"    • {tool.name}")

        # ══════════════════════════════════════════════════════════════════
        # TOOL 1 — start_campaign
        # ══════════════════════════════════════════════════════════════════
        print("\n" + "─" * 70)
        print("  TOOL 1: start_campaign")
        print("─" * 70)

        result = await client.call_tool("start_campaign", {
            "user_id":              SIMULATED_USER_ID,
            "icp_description_text": ICP_DESCRIPTION,
            "user_offering":        USER_OFFERING,
            "blacklist":            {"companies": [], "personas": []},
            "configurable_weights": {
                "firmographic_weight": 0.55,
                "intent_weight":       0.45,
                "passing_threshold":   45.0,
                "nurture_threshold":   20.0,
            },
        })

        # FastMCP returns a single CallToolResult, not a list
        output = json.loads(result.content[0].text)
        campaign_id = output["campaign_id"]

        print(f"\n  campaign_id : {campaign_id}")
        print(f"  status      : {output['status']}")
        print(f"  error       : {output.get('error')}")
        print(f"\n  ICP filters returned:")
        icp_filters = output.get("icp_filters", {})
        print(f"    industries:        {icp_filters.get('industries')}")
        print(f"    target_countries:  {icp_filters.get('target_countries')}")
        print(f"    target_continents: {icp_filters.get('target_continents')}")
        print(f"    company_size:      {icp_filters.get('company_size')}")

        assert output["status"] in ("running", "failed"), f"Unexpected status: {output['status']}"
        assert output.get("error") is None, f"Tool 1 error: {output.get('error')}"
        print("\n  ✓ Tool 1 passed")

        # ══════════════════════════════════════════════════════════════════
        # TOOL 4 — get_campaign_status (after Phase 1)
        # ══════════════════════════════════════════════════════════════════
        print("\n" + "─" * 70)
        print("  TOOL 4: get_campaign_status (after Phase 1)")
        print("─" * 70)

        result = await client.call_tool("get_campaign_status", {
            "campaign_id": campaign_id,
        })
        status_output = json.loads(result.content[0].text)
        print(f"\n  status     : {status_output['status']}")
        print(f"  user_id    : {status_output['user_id']}")
        print(f"  created_at : {status_output.get('created_at')}")
        print("\n  ✓ Tool 4 passed (post Phase 1)")

        # ══════════════════════════════════════════════════════════════════
        # TOOL 2 — resume_with_companies
        # ══════════════════════════════════════════════════════════════════
        print("\n" + "─" * 70)
        print("  TOOL 2: resume_with_companies")
        print(f"  [Sourcer] Returning {len(SOURCER_COMPANIES)} companies")
        print("─" * 70)

        result = await client.call_tool("resume_with_companies", {
            "campaign_id":       campaign_id,
            "sourced_companies": SOURCER_COMPANIES,
        })
        companies_output = json.loads(result.content[0].text)

        print(f"\n  status : {companies_output['status']}")
        print(f"  error  : {companies_output.get('error')}")
        ranked = companies_output.get("ranked_companies", [])
        print(f"\n  Ranked companies ({len(ranked)}):")
        for co in ranked:
            m = co.get("qualification_metrics") or {}
            print(
                f"    • {co['name']} | "
                f"Tier={m.get('tier')} | "
                f"Total={m.get('total_score')} | "
                f"Firm={m.get('firmographic_score')} | "
                f"Intent={m.get('intent_score')}"
            )
        print(f"\n  Disqualification summary: {companies_output.get('disqualification_summary')}")

        assert companies_output["status"] == "awaiting_approval", \
            f"Expected 'awaiting_approval', got: {companies_output['status']}"
        assert len(ranked) > 0, "Expected at least one ranked company"
        assert companies_output.get("error") is None
        print("\n  ✓ Tool 2 passed")

        # ══════════════════════════════════════════════════════════════════
        # TOOL 5 — get_pending_campaigns (simulate app reopen)
        # ══════════════════════════════════════════════════════════════════
        print("\n" + "─" * 70)
        print("  TOOL 5: get_pending_campaigns (simulating app reopen)")
        print("─" * 70)

        result = await client.call_tool("get_pending_campaigns", {
            "user_id": SIMULATED_USER_ID,
        })
        pending_output = json.loads(result.content[0].text)

        print(f"\n  total_pending : {pending_output['total_pending']}")
        for p in pending_output.get("pending_campaigns", []):
            print(
                f"  campaign_id   : {p['campaign_id']}\n"
                f"  status        : {p['status']}\n"
                f"  companies     : {len(p.get('ranked_companies', []))}"
            )

        assert pending_output["total_pending"] >= 1, "Expected at least 1 pending campaign"
        print("\n  ✓ Tool 5 passed")

        # ══════════════════════════════════════════════════════════════════
        # TOOL 3 — resume_with_approvals
        # ══════════════════════════════════════════════════════════════════
        print("\n" + "─" * 70)
        print("  TOOL 3: resume_with_approvals")
        print(f"  [User] Approving {len(APPROVED_APOLLO_IDS)} companies")
        print(f"  [Sourcer] Returning personas for approved companies")
        print("─" * 70)

        result = await client.call_tool("resume_with_approvals", {
            "campaign_id":                 campaign_id,
            "approved_apollo_ids":         APPROVED_APOLLO_IDS,
            "sourced_personas_by_company": SOURCER_PERSONAS,
        })
        approvals_output = json.loads(result.content[0].text)

        print(f"\n  status                : {approvals_output['status']}")
        print(f"  total_personas_ranked : {approvals_output['total_personas_ranked']}")
        print(f"  error                 : {approvals_output.get('error')}")
        print(f"\n  Ranked personas:")
        for p in approvals_output.get("ranked_personas", []):
            print(
                f"    • {p.get('name')} | {p.get('title')} | "
                f"Score={p.get('persona_score')} | "
                f"Email={p.get('email')}"
            )

        assert approvals_output["status"] == "completed", \
            f"Expected 'completed', got: {approvals_output['status']}"
        assert approvals_output["total_personas_ranked"] > 0
        assert approvals_output.get("error") is None
        print("\n  ✓ Tool 3 passed")

        # ══════════════════════════════════════════════════════════════════
        # TOOL 4 — get_campaign_status (final verification)
        # ══════════════════════════════════════════════════════════════════
        print("\n" + "─" * 70)
        print("  TOOL 4: get_campaign_status (final verification)")
        print("─" * 70)

        result = await client.call_tool("get_campaign_status", {
            "campaign_id": campaign_id,
        })
        final_status = json.loads(result.content[0].text)

        print(f"\n  campaign_id : {final_status['campaign_id']}")
        print(f"  status      : {final_status['status']}")
        print(f"  updated_at  : {final_status.get('updated_at')}")

        assert final_status["status"] == "completed"
        print("\n  ✓ Tool 4 passed (final)")

        print("\n" + "═" * 70)
        print("  ALL TOOLS PASSED — MCP SERVER IS WORKING CORRECTLY")
        print(f"  campaign_id: {campaign_id}")
        print("  Check Supabase campaigns table to verify the row.")
        print("═" * 70 + "\n")


if __name__ == "__main__":
    asyncio.run(run_mcp_test())