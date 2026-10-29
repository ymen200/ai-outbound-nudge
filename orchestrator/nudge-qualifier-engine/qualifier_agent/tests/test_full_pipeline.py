

# """
# tests/test_full_pipeline.py
# ────────────────────────────
# Full end-to-end pipeline test with interrupt simulation + campaign status tracking.

# What this test proves:
#   1. PostgresSaver checkpointer persists state across two separate pipeline calls.
#   2. CampaignStatusManager writes correct status transitions to the campaigns table.
#   3. get_pending_for_user() returns the right payload when the user "reopens the app".
#   4. Phase 2 resume correctly filters to approved companies only.
#   5. Status is correctly set to 'completed' at the end.

# After running this test, open your Supabase dashboard → Table Editor → campaigns
# and you should see one row with status = 'completed'.

# Run from project root:
#     python qualifier_agent/tests/test_full_pipeline.py
# """

# from __future__ import annotations

# import json
# import logging
# import os
# import sys
# import uuid
# from typing import Any, Dict, List

# ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# if ROOT_DIR not in sys.path:
#     sys.path.insert(0, ROOT_DIR)

# logging.basicConfig(level=logging.INFO, format="%(levelname)s | %(name)s | %(message)s")
# logger = logging.getLogger("test_full_pipeline")


# ROOT_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
# if ROOT_DIR not in sys.path:
#     sys.path.insert(0, ROOT_DIR)


# # ── ICP + offering ─────────────────────────────────────────────────────────────

# ICP_DESCRIPTION = """
# We are targeting mid-size insurance companies and fintech firms in France,
# specifically in Paris (including suburbs like Nanterre, La Défense) and Lyon.

# Must have:
# - Industry: Insurance, Fintech, Assurance, Financial Services
# - Company size: 500 to 20000 employees
# - Located in: France (Paris, Lyon, Nanterre, La Défense)

# Nice to have:
# - Revenue range: 100M to 50B EUR
# - Tech stack: Salesforce, SAP, Microsoft Teams, Python, Power BI

# Exclude:
# - Industries: Food & Beverage, Logistics, Retail, Wholesale
# - Keywords: foodservice, wholesale distribution, horeca
# - Company size: 1 to 10 employees (micro companies)

# Target roles:
# - Chief Revenue Officer
# - VP Sales
# - Head of Sales
# - Sales Director
# - Commercial Director

# Target departments:
# - Sales
# - Business Development
# - Commercial
# """

# USER_OFFERING = """
# LeadPulse is a B2B outbound sales automation platform that helps sales teams
# identify, qualify, and engage high-intent prospects using AI-driven scoring.
# It integrates with CRMs like Salesforce and HubSpot, automates personalized
# outreach sequences, and provides real-time intent signal tracking.
# Ideal for companies scaling their outbound sales motion with teams of 5+ SDRs.
# """


# # ── Raw company data ───────────────────────────────────────────────────────────

# RAW_COMPANIES: List[Dict[str, Any]] = [

#     {
#         "apollo_id":               "556936c873696421ab590d00",
#         "name":                    "AXA (Entité Nanterre)",
#         "domain":                  "axa.fr",
#         "website_url":             "https://www.axa.fr",
#         "industry":                "Assurance et Services Financiers",
#         "estimated_num_employees": 9000,
#         "annual_revenue":          31644000000,
#         "founded_year":            1971,
#         "city":                    "Nanterre",
#         "country":                 "France",
#         "state":                   "Ile-de-France",
#         "latest_funding_stage":    "Publicly Traded",
#         "is_subsidiary":           True,
#         "parent_company":          "AXA Group",
#         "full_description": (
#             "AXA (Entité Nanterre) is a leading insurance and financial services company "
#             "based in Nanterre, France. The company is actively expanding its digital sales "
#             "capabilities and investing in CRM modernization."
#         ),
#         "short_description": "Siège opérationnel et centre d'expertise technique pour les activités d'assurance",
#         "linkedin_url":      "https://www.linkedin.com/company/axa-france",
#         "data_quality_score": 0.94,
#         "technologies": json.dumps([
#             {"uid": "salesforce_crm", "name": "Salesforce CRM Analytics", "category": "CRM"},
#             {"uid": "sap",            "name": "SAP",                       "category": "ERP"},
#             {"uid": "microsoft_teams","name": "Microsoft Teams",           "category": "Collaboration"},
#             {"uid": "python",         "name": "Python",                    "category": "Programming"},
#             {"uid": "power_bi",       "name": "Power BI Documenter",       "category": "BI"},
#         ]),
#         "keywords": json.dumps(["insurance", "assurance", "CRM", "digital transformation", "B2B"]),
#         "funding_events": json.dumps([]),
#         "competitors":      json.dumps(["Allianz France", "Generali France"]),
#         "departments":      json.dumps({"sales": 423, "business_development": 43}),
#         "suborganizations": json.dumps([]),
#         "intent_signals": {
#             "job_offers": [
#                 {
#                     "title":       "Sales Development Representative (SDR)",
#                     "department":  "Sales",
#                     "posted_date": "2026-05-15",
#                     "description": "Looking for SDRs to scale our outbound B2B sales motion.",
#                 },
#             ],
#             "news": [
#                 {
#                     "headline":       "AXA France announces €200M digital transformation investment",
#                     "published_date": "2026-03-10",
#                     "summary":        "AXA France is investing heavily in digitalizing its sales processes.",
#                 },
#             ],
#         },
#     },

#     {
#         "apollo_id":               "bnp_tech_001",
#         "name":                    "BNP Paribas Tech & Innovation",
#         "domain":                  "bnpparibas.com",
#         "website_url":             "https://www.bnpparibas.com",
#         "industry":                "Fintech et Services Bancaires",
#         "estimated_num_employees": 5500,
#         "annual_revenue":          8200000000,
#         "founded_year":            2018,
#         "city":                    "Paris",
#         "country":                 "France",
#         "state":                   "Ile-de-France",
#         "latest_funding_stage":    "Publicly Traded",
#         "is_subsidiary":           True,
#         "parent_company":          "BNP Paribas Group",
#         "full_description": (
#             "BNP Paribas Tech & Innovation is the digital transformation arm of BNP Paribas, "
#             "focused on building next-generation fintech products and scaling digital banking services."
#         ),
#         "short_description":    "Division innovation et transformation digitale de BNP Paribas",
#         "linkedin_url":         "https://www.linkedin.com/company/bnp-paribas",
#         "data_quality_score":   0.91,
#         "technologies": json.dumps([
#             {"uid": "salesforce", "name": "Salesforce CRM Analytics", "category": "CRM"},
#             {"uid": "python",     "name": "Python",                   "category": "Programming"},
#             {"uid": "ms_teams",   "name": "Microsoft Teams",          "category": "Collaboration"},
#         ]),
#         "keywords": json.dumps(["fintech", "digital banking", "B2B sales", "CRM"]),
#         "funding_events": json.dumps([]),
#         "competitors":      json.dumps(["Société Générale", "Crédit Agricole"]),
#         "departments":      json.dumps({"sales": 380, "business_development": 95}),
#         "suborganizations": json.dumps([]),
#         "intent_signals": {
#             "job_offers": [
#                 {
#                     "title":       "Senior SDR - B2B Enterprise",
#                     "department":  "Sales",
#                     "posted_date": "2026-06-10",
#                     "description": "Building our outbound SDR team for enterprise B2B acquisition.",
#                 },
#             ],
#             "news": [],
#         },
#     },

#     {
#         "apollo_id":               "covea_lyon_001",
#         "name":                    "Covea Lyon",
#         "domain":                  "covea.fr",
#         "website_url":             "https://www.covea.fr",
#         "industry":                "Insurance",
#         "estimated_num_employees": 2800,
#         "annual_revenue":          3500000000,
#         "founded_year":            2003,
#         "city":                    "Lyon",
#         "country":                 "France",
#         "state":                   "Auvergne-Rhône-Alpes",
#         "latest_funding_stage":    "Private",
#         "is_subsidiary":           False,
#         "parent_company":          None,
#         "full_description": (
#             "Covea Lyon is the regional headquarters of Covea, one of France's largest mutual "
#             "insurance groups, managing insurance products for individual and corporate clients."
#         ),
#         "short_description":    "Siège régional de Covea pour la région Auvergne-Rhône-Alpes",
#         "linkedin_url":         "https://www.linkedin.com/company/covea",
#         "data_quality_score":   0.87,
#         "technologies": json.dumps([
#             {"uid": "sap",      "name": "SAP",             "category": "ERP"},
#             {"uid": "ms_teams", "name": "Microsoft Teams", "category": "Collaboration"},
#         ]),
#         "keywords":         json.dumps(["insurance", "assurance", "B2B", "corporate insurance"]),
#         "funding_events":   json.dumps([]),
#         "competitors":      json.dumps(["Groupama", "MAIF"]),
#         "departments":      json.dumps({"sales": 180, "business_development": 40}),
#         "suborganizations": json.dumps([]),
#         "intent_signals":   {"job_offers": [], "news": []},
#     },

#     {
#         "apollo_id":               "microassur_001",
#         "name":                    "MicroAssur",
#         "domain":                  "microassur.fr",
#         "website_url":             "https://www.microassur.fr",
#         "industry":                "Insurance",
#         "estimated_num_employees": 49,
#         "annual_revenue":          4200000,
#         "founded_year":            2019,
#         "city":                    "Paris",
#         "country":                 "France",
#         "state":                   "Ile-de-France",
#         "latest_funding_stage":    "Seed",
#         "is_subsidiary":           False,
#         "parent_company":          None,
#         "full_description":        "MicroAssur is a Paris-based insurtech startup for gig economy workers.",
#         "short_description":       "Insurtech micro-assurance pour travailleurs indépendants",
#         "linkedin_url":            "https://www.linkedin.com/company/microassur",
#         "data_quality_score":      0.78,
#         "technologies":            json.dumps([]),
#         "keywords":                json.dumps(["insurtech", "micro-insurance"]),
#         "funding_events":          json.dumps([]),
#         "competitors":             json.dumps([]),
#         "departments":             json.dumps({}),
#         "suborganizations":        json.dumps([]),
#         "intent_signals":          {"job_offers": [], "news": []},
#     },

#     {
#         "apollo_id":               "logifood_001",
#         "name":                    "LogiFood France",
#         "domain":                  "logifood.fr",
#         "website_url":             "https://www.logifood.fr",
#         "industry":                "Logistics & Food Distribution",
#         "estimated_num_employees": 1200,
#         "annual_revenue":          450000000,
#         "founded_year":            1998,
#         "city":                    "Paris",
#         "country":                 "France",
#         "state":                   "Ile-de-France",
#         "latest_funding_stage":    "Private",
#         "is_subsidiary":           False,
#         "parent_company":          None,
#         "full_description":        "LogiFood France is a wholesale food distribution company for the horeca sector.",
#         "short_description":       "Distribution alimentaire en gros pour le secteur horeca",
#         "linkedin_url":            "https://www.linkedin.com/company/logifood-france",
#         "data_quality_score":      0.82,
#         "technologies":            json.dumps([]),
#         "keywords":                json.dumps(["foodservice", "wholesale distribution", "horeca"]),
#         "funding_events":          json.dumps([]),
#         "competitors":             json.dumps([]),
#         "departments":             json.dumps({}),
#         "suborganizations":        json.dumps([]),
#         "intent_signals":          {"job_offers": [], "news": []},
#     },

#     {
#         "apollo_id":               "blacklisted_001",
#         "name":                    "Blacklisted Corp",
#         "domain":                  "blacklisted.fr",
#         "website_url":             "https://www.blacklisted.fr",
#         "industry":                "Insurance",
#         "estimated_num_employees": 3000,
#         "annual_revenue":          500000000,
#         "founded_year":            2000,
#         "city":                    "Paris",
#         "country":                 "France",
#         "state":                   "Ile-de-France",
#         "latest_funding_stage":    "Private",
#         "is_subsidiary":           False,
#         "parent_company":          None,
#         "full_description":        "A blacklisted company that should never pass the gate.",
#         "short_description":       "Blacklisted.",
#         "linkedin_url":            None,
#         "data_quality_score":      0.50,
#         "technologies":            json.dumps([]),
#         "keywords":                json.dumps([]),
#         "funding_events":          json.dumps([]),
#         "competitors":             json.dumps([]),
#         "departments":             json.dumps({}),
#         "suborganizations":        json.dumps([]),
#         "intent_signals":          {"job_offers": [], "news": []},
#     },
# ]


# # ── Personas (sourcer delivers after approval) ────────────────────────────────

# PERSONAS_BY_COMPANY: Dict[str, List[Dict[str, Any]]] = {
#     "556936c873696421ab590d00": [
#         {
#             "name":                  "Marie Dupont",
#             "title":                 "VP Sales France",
#             "seniority":             "VP",
#             "department":            "Sales",
#             "months_in_role":        18,
#             "is_linkedin_connected": True,
#             "email":                 "m.dupont@axa.fr",
#             "phone_number":          "+33 6 12 34 56 78",
#             "public_signals":        "Recently posted about scaling outbound sales teams using AI tools.",
#         },
#         {
#             "name":                  "Sophie Leclerc",
#             "title":                 "Chief Revenue Officer",
#             "seniority":             "C-Level",
#             "department":            "Sales",
#             "months_in_role":        8,
#             "is_linkedin_connected": False,
#             "email":                 "s.leclerc@axa.fr",
#             "phone_number":          "+33 6 98 76 54 32",
#             "public_signals":        "New CRO focused on building scalable revenue processes.",
#         },
#     ],
#     "covea_lyon_001": [
#         {
#             "name":                  "Isabelle Moreau",
#             "title":                 "Directrice Commerciale",
#             "seniority":             "Director",
#             "department":            "Sales",
#             "months_in_role":        36,
#             "is_linkedin_connected": True,
#             "email":                 "i.moreau@covea.fr",
#             "phone_number":          "+33 4 72 00 11 22",
#             "public_signals":        "Long-tenured sales director managing a team of 40 reps.",
#         },
#     ],
# }


# # ── Simulated user selections ─────────────────────────────────────────────────

# # User approves AXA and Covea, declines BNP
# APPROVED_APOLLO_IDS = [
#     "556936c873696421ab590d00",  # AXA
#     "covea_lyon_001",             # Covea Lyon
# ]
# SIMULATED_USER_ID = "user-test-001"


# # ── Test runner ───────────────────────────────────────────────────────────────

# def run_full_pipeline_test():
#     from langgraph.types import Command
#     from graph.workflow import get_pipeline
#     from graph.campaign_status import CampaignStatusManager, CampaignStatus

#     manager     = CampaignStatusManager()
#     campaign_id = str(uuid.uuid4())
#     config      = {"configurable": {"thread_id": campaign_id}}

#     print("\n" + "═" * 70)
#     print("  LEADPULSE — STRATEGIC QUALIFIER PIPELINE TEST")
#     print(f"  campaign_id: {campaign_id}")
#     print("═" * 70)

#     # ── Create campaign record ─────────────────────────────────────────────
#     manager.create(
#         campaign_id=campaign_id,
#         user_id=SIMULATED_USER_ID,
#         icp_description=ICP_DESCRIPTION,
#     )
#     print(f"\n  [DB] Campaign created → status = '{CampaignStatus.RUNNING}'")

#     initial_state = {
#         "icp_description_text":        ICP_DESCRIPTION,
#         "user_offering":               USER_OFFERING,
#         "campaign_id":                 campaign_id,
#         "sourced_companies":           RAW_COMPANIES,
#         "sourced_personas":            [],
#         "sourced_personas_by_company": None,
#         "blacklist": {
#             "companies": ["Blacklisted Corp", "blacklisted"],
#             "personas":  [],
#         },
#         "configurable_weights": {
#             "firmographic_weight": 0.55,
#             "intent_weight":       0.45,
#             "passing_threshold":   45.0,
#             "nurture_threshold":   20.0,
#             "near_miss_penalty":   0.20,
#             "near_miss_band":      0.10,
#         },
#         "user_approved_companies": None,
#         "pipeline_error":          None,
#     }

#     with get_pipeline() as pipeline:

#         # ── PHASE 1: Run until interrupt ───────────────────────────────────
#         print("\n▶  PHASE 1: Running pipeline nodes 1–4 + human_review...\n")

#         try:
#             for _ in pipeline.stream(initial_state, config, stream_mode="values"):
#                 pass
#         except Exception:
#             pass  # interrupt fires as an exception inside stream()

#         snapshot         = pipeline.get_state(config)
#         current          = snapshot.values
#         ranked           = current.get("ranked_companies", [])
#         nurture          = current.get("nurture_companies", [])
#         disq_log         = current.get("disqualification_log", {})
#         pipeline_error   = current.get("pipeline_error")

#         # ── Update DB: awaiting approval ───────────────────────────────────
#         if pipeline_error:
#             manager.set_failed(campaign_id, pipeline_error)
#             print(f"\n  [DB] Pipeline error → status = '{CampaignStatus.FAILED}'")
#             print(f"       Error: {pipeline_error}")
#             return

#         # Build the same trimmed payload human_review_node sends the frontend
#         review_payload = [
#             {
#                 "apollo_id":             co.get("apollo_id"),
#                 "name":                  co.get("name"),
#                 "domain":                co.get("domain"),
#                 "qualification_metrics": co.get("qualification_metrics", {}),
#                 "is_subsidiary":         co.get("is_subsidiary", False),
#                 "parent_company":        co.get("parent_company"),
#             }
#             for co in ranked
#         ]
#         manager.set_awaiting_approval(campaign_id, review_payload)
#         print(f"  [DB] Phase 1 complete → status = '{CampaignStatus.AWAITING_APPROVAL}'")

#         # ── Print Phase 1 results ──────────────────────────────────────────
#         print("\n" + "─" * 70)
#         print("  PHASE 1 RESULTS")
#         print("─" * 70)

#         print(f"\n  Ranked companies ({len(ranked)}):")
#         for co in ranked:
#             m = co.get("qualification_metrics", {})
#             subsidiary_note = (
#                 f" [SUBSIDIARY of {co.get('parent_company')}]"
#                 if co.get("is_subsidiary") else ""
#             )
#             print(
#                 f"    • {co['name']}{subsidiary_note}\n"
#                 f"      Tier={m.get('tier')} | Total={m.get('total_score')} "
#                 f"| Firm={m.get('firmographic_score')} | Intent={m.get('intent_score')}"
#             )
#             for feature, detail in m.get("breakdown", {}).items():
#                 print(
#                     f"        {feature}: "
#                     f"score={detail.get('score')} "
#                     f"quality={detail.get('match_quality')}"
#                 )

#         print(f"\n  Nurture companies ({len(nurture)}):")
#         for co in nurture:
#             m = co.get("qualification_metrics", {})
#             print(f"    • {co['name']} | Firm={m.get('firmographic_score')}")

#         print(f"\n  Disqualification summary:")
#         for code, count in disq_log.get("summary", {}).items():
#             print(f"    {code}: {count}")

#         # ── Simulate: app closed and reopened ─────────────────────────────
#         print("\n" + "─" * 70)
#         print("  SIMULATING: USER CLOSES APP AND REOPENS LATER")
#         print("─" * 70)

#         pending = manager.get_pending_for_user(SIMULATED_USER_ID)
#         print(f"\n  [Frontend] get_pending_for_user('{SIMULATED_USER_ID}') returned {len(pending)} campaign(s).")

#         if pending:
#             p = pending[0]
#             print(f"  [Frontend] Campaign '{p['campaign_id']}' is awaiting approval.")
#             print(f"  [Frontend] Rendering {len(p['ranked_companies'])} companies for review...")
#             print(f"  [Frontend] Status in DB: {p['status']}")

#         # ── Orchestrator simulation ────────────────────────────────────────
#         print("\n" + "─" * 70)
#         print("  HUMAN REVIEW + ORCHESTRATOR SIMULATION")
#         print("─" * 70)
#         print(f"\n  [User]          Approving: AXA + Covea Lyon")
#         print(f"  [User]          Declining: BNP Paribas Tech & Innovation")
#         print(f"  [Orchestrator]  Fetching personas for {len(APPROVED_APOLLO_IDS)} approved companies...")
#         print(f"  [Orchestrator]  Injecting personas into state...")

#         # Mark as resuming in DB before calling resume
#         manager.set_resuming(campaign_id)
#         print(f"  [DB] → status = '{CampaignStatus.RESUMING}'")

#         # ── PHASE 2: Inject personas + resume ─────────────────────────────
#         print("\n▶  PHASE 2: Resuming pipeline → node 5 running...\n")

#         pipeline.update_state(
#             config,
#             {"sourced_personas_by_company": PERSONAS_BY_COMPANY},
#         )

#         try:
#             for _ in pipeline.stream(
#                 Command(resume=APPROVED_APOLLO_IDS),
#                 config,
#                 stream_mode="values",
#             ):
#                 pass
#         except Exception as exc:
#             manager.set_failed(campaign_id, str(exc))
#             print(f"\n  [DB] Phase 2 failed → status = '{CampaignStatus.FAILED}'")
#             raise

#         # Mark as completed
#         manager.set_completed(campaign_id)
#         print(f"  [DB] Phase 2 complete → status = '{CampaignStatus.COMPLETED}'")

#         # ── Print Phase 2 results ──────────────────────────────────────────
#         final_state     = pipeline.get_state(config).values
#         ranked_personas = final_state.get("ranked_personas", [])

#         print("\n" + "─" * 70)
#         print("  PHASE 2 RESULTS — PERSONA RANKING")
#         print("─" * 70)

#         approved_companies = [
#             co for co in final_state.get("sourced_companies", [])
#             if co.get("apollo_id") in set(APPROVED_APOLLO_IDS)
#         ]

#         for co in approved_companies:
#             leads = co.get("ranked_target_leads", [])
#             print(f"\n  {co.get('name')} — {len(leads)} ranked persona(s):")
#             for p in leads:
#                 print(
#                     f"    • {p.get('name')} | {p.get('title')}\n"
#                     f"      Score={p.get('persona_score', 'N/A')} | "
#                     f"Seniority={p.get('seniority')} | "
#                     f"Email={p.get('email')}"
#                 )

#         print(f"\n  Total ranked personas: {len(ranked_personas)}")

#         # ── Final DB state verification ────────────────────────────────────
#         print("\n" + "─" * 70)
#         print("  FINAL DATABASE STATE VERIFICATION")
#         print("─" * 70)

#         final_db_row = manager.get(campaign_id)
#         print(f"\n  campaign_id : {final_db_row['campaign_id']}")
#         print(f"  user_id     : {final_db_row['user_id']}")
#         print(f"  status      : {final_db_row['status']}")
#         print(f"  created_at  : {final_db_row['created_at']}")
#         print(f"  updated_at  : {final_db_row['updated_at']}")
#         print(f"  ranked_companies in DB: {final_db_row['ranked_companies']}")

#         print("\n" + "═" * 70)
#         print("  TEST COMPLETE")
#         print("  Check your Supabase dashboard → campaigns table to verify.")
#         print("═" * 70 + "\n")


# if __name__ == "__main__":
#     run_full_pipeline_test()







"""
tests/test_full_pipeline.py
────────────────────────────
Full end-to-end pipeline test with two interrupts + campaign status tracking.

Flow:
  Phase 1: Node 1 runs → pauses at company_sourcing_node
           Pipeline returns ICP filters to orchestrator
           Orchestrator sends filters to sourcer → sourcer returns raw companies

  Phase 2: Orchestrator feeds raw companies back → Nodes 2-4 run
           Pipeline pauses at human_review_node
           Frontend shows ranked companies to user → user approves some

  Phase 3: Orchestrator sends approved IDs to sourcer → sourcer returns personas
           Orchestrator feeds personas back → Node 5 runs
           Pipeline completes

Run from project root:
    python qualifier_agent/tests/test_full_pipeline.py
"""

from __future__ import annotations

import json
import logging
import os
import sys
import uuid
from typing import Any, Dict, List

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

logging.basicConfig(level=logging.INFO, format="%(levelname)s | %(name)s | %(message)s")
logger = logging.getLogger("test_full_pipeline")


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
- Company size: 1 to 10 employees (micro companies)

Target roles:
- Chief Revenue Officer
- VP Sales
- Head of Sales
- Sales Director
- Commercial Director

Target departments:
- Sales
- Business Development
- Commercial
"""

USER_OFFERING = """
LeadPulse is a B2B outbound sales automation platform that helps sales teams
identify, qualify, and engage high-intent prospects using AI-driven scoring.
It integrates with CRMs like Salesforce and HubSpot, automates personalized
outreach sequences, and provides real-time intent signal tracking.
Ideal for companies scaling their outbound sales motion with teams of 5+ SDRs.
"""


# ── Mock sourcer response — raw companies ──────────────────────────────────────

SOURCER_COMPANIES: List[Dict[str, Any]] = [
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
        "full_description": (
            "AXA (Entité Nanterre) is a leading insurance and financial services company "
            "based in Nanterre, France. The company is actively expanding its digital sales "
            "capabilities and investing in CRM modernization."
        ),
        "short_description": "Siège opérationnel et centre d'expertise technique pour les activités d'assurance",
        "linkedin_url":      "https://www.linkedin.com/company/axa-france",
        "data_quality_score": 0.94,
        "technologies": json.dumps([
            {"uid": "salesforce_crm", "name": "Salesforce CRM Analytics", "category": "CRM"},
            {"uid": "sap",            "name": "SAP",                       "category": "ERP"},
            {"uid": "microsoft_teams","name": "Microsoft Teams",           "category": "Collaboration"},
            {"uid": "python",         "name": "Python",                    "category": "Programming"},
            {"uid": "power_bi",       "name": "Power BI Documenter",       "category": "BI"},
        ]),
        "keywords":         json.dumps(["insurance", "assurance", "CRM", "digital transformation", "B2B"]),
        "funding_events":   json.dumps([]),
        "competitors":      json.dumps(["Allianz France", "Generali France"]),
        "departments":      json.dumps({"sales": 423, "business_development": 43}),
        "suborganizations": json.dumps([]),
        "intent_signals": {
            "job_offers": [
                {
                    "title":       "Sales Development Representative (SDR)",
                    "department":  "Sales",
                    "posted_date": "2026-05-15",
                    "description": "Looking for SDRs to scale our outbound B2B sales motion.",
                },
            ],
            "news": [
                {
                    "headline":       "AXA France announces €200M digital transformation investment",
                    "published_date": "2026-03-10",
                    "summary":        "AXA France is investing heavily in digitalizing its sales processes.",
                },
            ],
        },
    },
    {
        "apollo_id":               "bnp_tech_001",
        "name":                    "BNP Paribas Tech & Innovation",
        "domain":                  "bnpparibas.com",
        "website_url":             "https://www.bnpparibas.com",
        "industry":                "Fintech et Services Bancaires",
        "estimated_num_employees": 5500,
        "annual_revenue":          8200000000,
        "founded_year":            2018,
        "city":                    "Paris",
        "country":                 "France",
        "state":                   "Ile-de-France",
        "latest_funding_stage":    "Publicly Traded",
        "is_subsidiary":           True,
        "parent_company":          "BNP Paribas Group",
        "full_description": (
            "BNP Paribas Tech & Innovation is the digital transformation arm of BNP Paribas, "
            "focused on building next-generation fintech products and scaling digital banking services."
        ),
        "short_description":    "Division innovation et transformation digitale de BNP Paribas",
        "linkedin_url":         "https://www.linkedin.com/company/bnp-paribas",
        "data_quality_score":   0.91,
        "technologies": json.dumps([
            {"uid": "salesforce", "name": "Salesforce CRM Analytics", "category": "CRM"},
            {"uid": "python",     "name": "Python",                   "category": "Programming"},
            {"uid": "ms_teams",   "name": "Microsoft Teams",          "category": "Collaboration"},
        ]),
        "keywords":         json.dumps(["fintech", "digital banking", "B2B sales", "CRM"]),
        "funding_events":   json.dumps([]),
        "competitors":      json.dumps(["Société Générale", "Crédit Agricole"]),
        "departments":      json.dumps({"sales": 380, "business_development": 95}),
        "suborganizations": json.dumps([]),
        "intent_signals": {
            "job_offers": [
                {
                    "title":       "Senior SDR - B2B Enterprise",
                    "department":  "Sales",
                    "posted_date": "2026-06-10",
                    "description": "Building our outbound SDR team for enterprise B2B acquisition.",
                },
            ],
            "news": [],
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
        "full_description": (
            "Covea Lyon is the regional headquarters of Covea, one of France's largest mutual "
            "insurance groups, managing insurance products for individual and corporate clients."
        ),
        "short_description":    "Siège régional de Covea pour la région Auvergne-Rhône-Alpes",
        "linkedin_url":         "https://www.linkedin.com/company/covea",
        "data_quality_score":   0.87,
        "technologies": json.dumps([
            {"uid": "sap",      "name": "SAP",             "category": "ERP"},
            {"uid": "ms_teams", "name": "Microsoft Teams", "category": "Collaboration"},
        ]),
        "keywords":         json.dumps(["insurance", "assurance", "B2B", "corporate insurance"]),
        "funding_events":   json.dumps([]),
        "competitors":      json.dumps(["Groupama", "MAIF"]),
        "departments":      json.dumps({"sales": 180, "business_development": 40}),
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
        "full_description":        "MicroAssur is a Paris-based insurtech startup for gig economy workers.",
        "short_description":       "Insurtech micro-assurance pour travailleurs indépendants",
        "linkedin_url":            "https://www.linkedin.com/company/microassur",
        "data_quality_score":      0.78,
        "technologies":            json.dumps([]),
        "keywords":                json.dumps(["insurtech", "micro-insurance"]),
        "funding_events":          json.dumps([]),
        "competitors":             json.dumps([]),
        "departments":             json.dumps({}),
        "suborganizations":        json.dumps([]),
        "intent_signals":          {"job_offers": [], "news": []},
    },
    {
        "apollo_id":               "logifood_001",
        "name":                    "LogiFood France",
        "domain":                  "logifood.fr",
        "website_url":             "https://www.logifood.fr",
        "industry":                "Logistics & Food Distribution",
        "estimated_num_employees": 1200,
        "annual_revenue":          450000000,
        "founded_year":            1998,
        "city":                    "Paris",
        "country":                 "France",
        "state":                   "Ile-de-France",
        "latest_funding_stage":    "Private",
        "is_subsidiary":           False,
        "parent_company":          None,
        "full_description":        "LogiFood France is a wholesale food distribution company for the horeca sector.",
        "short_description":       "Distribution alimentaire en gros pour le secteur horeca",
        "linkedin_url":            "https://www.linkedin.com/company/logifood-france",
        "data_quality_score":      0.82,
        "technologies":            json.dumps([]),
        "keywords":                json.dumps(["foodservice", "wholesale distribution", "horeca"]),
        "funding_events":          json.dumps([]),
        "competitors":             json.dumps([]),
        "departments":             json.dumps({}),
        "suborganizations":        json.dumps([]),
        "intent_signals":          {"job_offers": [], "news": []},
    },
    {
        "apollo_id":               "blacklisted_001",
        "name":                    "Blacklisted Corp",
        "domain":                  "blacklisted.fr",
        "website_url":             "https://www.blacklisted.fr",
        "industry":                "Insurance",
        "estimated_num_employees": 3000,
        "annual_revenue":          500000000,
        "founded_year":            2000,
        "city":                    "Paris",
        "country":                 "France",
        "state":                   "Ile-de-France",
        "latest_funding_stage":    "Private",
        "is_subsidiary":           False,
        "parent_company":          None,
        "full_description":        "A blacklisted company that should never pass the gate.",
        "short_description":       "Blacklisted.",
        "linkedin_url":            None,
        "data_quality_score":      0.50,
        "technologies":            json.dumps([]),
        "keywords":                json.dumps([]),
        "funding_events":          json.dumps([]),
        "competitors":             json.dumps([]),
        "departments":             json.dumps({}),
        "suborganizations":        json.dumps([]),
        "intent_signals":          {"job_offers": [], "news": []},
    },
]


# ── Mock sourcer personas response ─────────────────────────────────────────────

SOURCER_PERSONAS: Dict[str, List[Dict[str, Any]]] = {
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
            "public_signals":        "Recently posted about scaling outbound sales teams using AI tools.",
        },
        {
            "name":                  "Sophie Leclerc",
            "title":                 "Chief Revenue Officer",
            "seniority":             "C-Level",
            "department":            "Sales",
            "months_in_role":        8,
            "is_linkedin_connected": False,
            "email":                 "s.leclerc@axa.fr",
            "phone_number":          "+33 6 98 76 54 32",
            "public_signals":        "New CRO focused on building scalable revenue processes.",
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
            "public_signals":        "Long-tenured sales director managing a team of 40 reps.",
        },
    ],
}

APPROVED_APOLLO_IDS = [
    "556936c873696421ab590d00",
    "covea_lyon_001",
]

SIMULATED_USER_ID = "user-test-001"


# ── Test runner ───────────────────────────────────────────────────────────────

def run_full_pipeline_test():
    from langgraph.types import Command
    from graph.workflow import get_pipeline
    from graph.campaign_status import CampaignStatusManager, CampaignStatus

    manager     = CampaignStatusManager()
    campaign_id = str(uuid.uuid4())
    config      = {"configurable": {"thread_id": campaign_id}}

    print("\n" + "═" * 70)
    print("  LEADPULSE — STRATEGIC QUALIFIER PIPELINE TEST (3-phase)")
    print(f"  campaign_id: {campaign_id}")
    print("═" * 70)

    manager.create(
        campaign_id=campaign_id,
        user_id=SIMULATED_USER_ID,
        icp_description=ICP_DESCRIPTION,
    )
    print(f"\n  [DB] Campaign created → status = '{CampaignStatus.RUNNING}'")

    # sourced_companies starts empty — sourcer fills it after Phase 1
    initial_state = {
        "icp_description_text":        ICP_DESCRIPTION,
        "user_offering":               USER_OFFERING,
        "campaign_id":                 campaign_id,
        "sourced_companies":           [],
        "sourced_personas":            [],
        "sourced_personas_by_company": None,
        "blacklist": {
            "companies": ["Blacklisted Corp", "blacklisted"],
            "personas":  [],
        },
        "configurable_weights": {
            "firmographic_weight": 0.55,
            "intent_weight":       0.45,
            "passing_threshold":   45.0,
            "nurture_threshold":   20.0,
            "near_miss_penalty":   0.20,
            "near_miss_band":      0.10,
        },
        "user_approved_companies": None,
        "pipeline_error":          None,
    }

    with get_pipeline() as pipeline:

        # ══════════════════════════════════════════════════════════════════
        # PHASE 1 — Node 1 runs, pauses at company_sourcing_node
        # ══════════════════════════════════════════════════════════════════
        print("\n▶  PHASE 1: Running Node 1 (ICP extraction)...\n")

        try:
            for _ in pipeline.stream(initial_state, config, stream_mode="values"):
                pass
        except Exception:
            pass

        snapshot       = pipeline.get_state(config)
        current        = snapshot.values
        pipeline_error = current.get("pipeline_error")

        if pipeline_error:
            manager.set_failed(campaign_id, pipeline_error)
            print(f"\n  [DB] Pipeline error → status = '{CampaignStatus.FAILED}'")
            print(f"       Error: {pipeline_error}")
            return

        # Read interrupt payload from snapshot tasks
        interrupt_payload = None
        if snapshot.tasks:
            for task in snapshot.tasks:
                if hasattr(task, "interrupts") and task.interrupts:
                    interrupt_payload = task.interrupts[0].value
                    break

        print("\n" + "─" * 70)
        print("  PHASE 1 RESULTS — ICP EXTRACTION")
        print("─" * 70)

        extracted_icp = current.get("extracted_icp")
        if extracted_icp:
            print(f"\n  Extracted ICP:")
            print(f"    industries:        {extracted_icp.must_have.industry}")
            print(f"    target_countries:  {extracted_icp.must_have.target_countries}")
            print(f"    target_continents: {extracted_icp.must_have.target_continents}")
            size = getattr(extracted_icp.must_have, "company_size", None)
            if size:
                print(f"    company_size:      min={size.min} max={size.max}")

        if interrupt_payload:
            print(f"\n  Interrupt payload sent to orchestrator:")
            print(f"    type:        {interrupt_payload.get('type')}")
            print(f"    icp_filters: {interrupt_payload.get('icp_filters')}")

        print("\n" + "─" * 70)
        print("  ORCHESTRATOR: Sending ICP filters to sourcer...")
        print("─" * 70)
        print(f"\n  [Sourcer] Querying Apollo...")
        print(f"  [Sourcer] Returning {len(SOURCER_COMPANIES)} raw companies")

        # ══════════════════════════════════════════════════════════════════
        # PHASE 2 — Resume with companies, Nodes 2-4 run, pauses at human_review
        # ══════════════════════════════════════════════════════════════════
        print("\n▶  PHASE 2: Resuming with sourced companies (Nodes 2-4)...\n")

        try:
            for _ in pipeline.stream(
                Command(resume=SOURCER_COMPANIES),
                config,
                stream_mode="values",
            ):
                pass
        except Exception:
            pass

        snapshot2      = pipeline.get_state(config)
        current2       = snapshot2.values
        pipeline_error = current2.get("pipeline_error")

        if pipeline_error:
            manager.set_failed(campaign_id, pipeline_error)
            print(f"\n  [DB] Pipeline error → status = '{CampaignStatus.FAILED}'")
            print(f"       Error: {pipeline_error}")
            return

        ranked   = current2.get("ranked_companies", [])
        nurture  = current2.get("nurture_companies", [])
        disq_log = current2.get("disqualification_log", {})

        review_payload = [
            {
                "apollo_id":             co.get("apollo_id"),
                "name":                  co.get("name"),
                "domain":                co.get("domain"),
                "qualification_metrics": co.get("qualification_metrics", {}),
                "is_subsidiary":         co.get("is_subsidiary", False),
                "parent_company":        co.get("parent_company"),
            }
            for co in ranked
        ]
        manager.set_awaiting_approval(campaign_id, review_payload)
        print(f"  [DB] Phase 2 complete → status = '{CampaignStatus.AWAITING_APPROVAL}'")

        print("\n" + "─" * 70)
        print("  PHASE 2 RESULTS — RANKED COMPANIES")
        print("─" * 70)

        print(f"\n  Ranked companies ({len(ranked)}):")
        for co in ranked:
            m = co.get("qualification_metrics", {})
            subsidiary_note = (
                f" [SUBSIDIARY of {co.get('parent_company')}]"
                if co.get("is_subsidiary") else ""
            )
            print(
                f"    • {co['name']}{subsidiary_note}\n"
                f"      Tier={m.get('tier')} | Total={m.get('total_score')} "
                f"| Firm={m.get('firmographic_score')} | Intent={m.get('intent_score')}"
            )
            for feature, detail in m.get("breakdown", {}).items():
                print(
                    f"        {feature}: score={detail.get('score')} "
                    f"quality={detail.get('match_quality')}"
                )

        print(f"\n  Nurture companies ({len(nurture)}):")
        for co in nurture:
            m = co.get("qualification_metrics", {})
            print(f"    • {co['name']} | Firm={m.get('firmographic_score')}")

        print(f"\n  Disqualification summary:")
        for code, count in disq_log.get("summary", {}).items():
            print(f"    {code}: {count}")

        # ── Simulate app reopen ────────────────────────────────────────────
        print("\n" + "─" * 70)
        print("  SIMULATING: USER CLOSES APP AND REOPENS LATER")
        print("─" * 70)
        pending = manager.get_pending_for_user(SIMULATED_USER_ID)
        print(f"\n  [Frontend] get_pending_for_user() → {len(pending)} campaign(s) pending")
        if pending:
            p = pending[0]
            print(f"  [Frontend] Rendering {len(p['ranked_companies'])} companies for approval")
            print(f"  [Frontend] DB status: {p['status']}")

        # ══════════════════════════════════════════════════════════════════
        # PHASE 3 — User approves, sourcer returns personas, Node 5 runs
        # ══════════════════════════════════════════════════════════════════
        print("\n" + "─" * 70)
        print("  HUMAN REVIEW + ORCHESTRATOR SIMULATION")
        print("─" * 70)
        print(f"\n  [User]          Approving: AXA + Covea Lyon")
        print(f"  [User]          Declining: BNP Paribas Tech & Innovation")
        print(f"  [Orchestrator]  Sending approved_ids to sourcer for personas...")
        print(f"  [Sourcer]       Returning personas for {len(APPROVED_APOLLO_IDS)} companies")
        print(f"  [Orchestrator]  Injecting personas into state...")

        manager.set_resuming(campaign_id)
        print(f"  [DB] → status = '{CampaignStatus.RESUMING}'")

        print("\n▶  PHASE 3: Resuming with approvals → Node 5 running...\n")

        pipeline.update_state(
            config,
            {"sourced_personas_by_company": SOURCER_PERSONAS},
        )

        try:
            for _ in pipeline.stream(
                Command(resume=APPROVED_APOLLO_IDS),
                config,
                stream_mode="values",
            ):
                pass
        except Exception as exc:
            manager.set_failed(campaign_id, str(exc))
            print(f"\n  [DB] Phase 3 failed → status = '{CampaignStatus.FAILED}'")
            raise

        manager.set_completed(campaign_id)
        print(f"  [DB] Phase 3 complete → status = '{CampaignStatus.COMPLETED}'")

        final_state     = pipeline.get_state(config).values
        ranked_personas = final_state.get("ranked_personas", [])

        print("\n" + "─" * 70)
        print("  PHASE 3 RESULTS — PERSONA RANKING")
        print("─" * 70)
        print(f"\n  Total ranked personas: {len(ranked_personas)}")
        for p in ranked_personas:
            print(
                f"    • {p.get('name')} | {p.get('title')}\n"
                f"      Score={p.get('persona_score', 'N/A')} | "
                f"Seniority={p.get('seniority')} | "
                f"Email={p.get('email')}"
            )

        print("\n" + "─" * 70)
        print("  FINAL DATABASE STATE")
        print("─" * 70)
        row = manager.get(campaign_id)
        print(f"\n  campaign_id : {row['campaign_id']}")
        print(f"  user_id     : {row['user_id']}")
        print(f"  status      : {row['status']}")
        print(f"  created_at  : {row['created_at']}")
        print(f"  updated_at  : {row['updated_at']}")

        print("\n" + "═" * 70)
        print("  TEST COMPLETE — check Supabase campaigns table to verify.")
        print("═" * 70 + "\n")


if __name__ == "__main__":
    run_full_pipeline_test()