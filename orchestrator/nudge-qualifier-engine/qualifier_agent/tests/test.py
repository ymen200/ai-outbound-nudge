# # test_pipeline.py

# import os
# import sys
# from datetime import datetime, timedelta

# # Dynamically ensure root directory is accessible for imports
# ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# if ROOT_DIR not in sys.path:
#     sys.path.insert(0, ROOT_DIR)
# from graph.state import CampaignState

# # ── Sample Company with Intent Signals ────────────────────────────────────────

# def get_test_company_data():
#     """
#     AXA (Entité Nanterre) — Insurance company with intent signals
#     """
#     # Generate recent timestamps for intent signals
#     now = datetime.now()
#     week_ago = now - timedelta(days=7)
#     two_weeks_ago = now - timedelta(days=14)
    
#     return {
#         "apollo_id": "556936c873696421ab590d00",
#         "name": "AXA (Entité Nanterre)",
#         "domain": "metro.fr",
#         "website_url": "http://www.metro.fr",
        
#         # Industry
#         "industry": "Assurance et Services Financiers",
        
#         # Size & Revenue
#         "estimated_num_employees": 9000,
#         "annual_revenue": 31644000000,
#         "founded_year": 1971,
        
#         # Location
#         "city": "Nanterre",
#         "country": "France",
#         "state": "Ile-de-France",
#         "postal_code": "92000",
#         "street_address": "5 Rue des Grands-Pres",
#         "raw_address": "5 Rue des Grands-Pres, Nanterre, France",
        
#         # Funding
#         "latest_funding_stage": "Publicly Traded",
#         "funding_events": '[{"id": "693558c29bf5f9000165070a", "date": "2021-01-01T00:00:00.000+00:00", "type": "Other", "amount": "Non renseigné", "currency": "$", "investors": "Non renseigné"}]',
        
#         # Enrichment
#         "technologies": '[{"uid": "python", "name": "Python", "category": "Frameworks and Programming Languages"}, {"uid": "sap", "name": "SAP", "category": "Customer Relationship Management"}, {"uid": "microsoft_teams", "name": "Microsoft Teams", "category": "Communication and Collaboration"}, {"uid": "salesforce crm analytics", "name": "Salesforce CRM Analytics", "category": "Analytics and Tracking"}, {"uid": "power_bi_documenter", "name": "Power BI Documenter", "category": "Analytics and Tracking"}]',
        
#         "competitors": '["Allianz France", "Generali France", "Groupama", "Swiss Life France", "CNP Assurances"]',
        
#         "departments": '{"sales": 423, "information_technology": 25, "consulting": 113, "operations": 104, "human_resources": 88, "finance": 49, "support": 267, "engineering": 24, "marketing": 22, "business_development": 43}',
        
#         "keywords": '["Assurance", "Gestion d\'actifs", "Nanterre HQ", "AXA France", "Expertise Technique", "sustainability", "digital platforms", "business growth", "operational efficiency", "customer support"]',
        
#         # Descriptions
#         "full_description": "AXA (Entité Nanterre) is a leading operational hub and technical expertise center for insurance activities, situated in France. As a prominent player in the Assurance et Services Financiers industry, the company leverages cutting-edge technologies such as GIS, .NET, 24-7 Media, AI, and Adobe to drive innovation and excellence. With an estimated 9,000 employees and annual revenue of approximately €31.644 billion, AXA (Entité Nanterre) plays a significant role in shaping the wholesale distribution landscape in France, with a focus on sustainability, inventory management, and B2B commerce.",
        
#         "short_description": "Siège opérationnel et centre d'expertise technique pour les activités d'assurance",
        
#         # Subsidiary info
#         "is_subsidiary": True,
#         "parent_company": "AXA Group",
#         "num_suborganizations": 3,
#         "suborganizations": '[{"id": "Non renseigné", "name": "AXA France IARD", "domain": "Non renseigné"}, {"id": "Non renseigné", "name": "AXA France Vie", "domain": "Non renseigné"}, {"id": "Non renseigné", "name": "AXA Group Operations", "domain": "Non renseigné"}]',
        
#         # Meta
#         "linkedin_url": "http://www.linkedin.com/company/metro-france",
#         "twitter_url": "https://twitter.com/axafrance",
#         "logo_url": "https://zenprospect-production.s3.amazonaws.com/uploads/pictures/695e0a898a20160001ca56f0/picture",
#         "data_quality_score": 0.94,
#         "alexa_ranking": 38580,
#         "phone": "+33 825 09 09 09",
#         "fiscal_year_end": "December",
#         "source": "Merged_Apollo_AI",
#         "captured_at": "2026-06-14T17:40:57.686000000Z",
        
#         # ── INTENT SIGNALS (Added) ────────────────────────────────────────
#         "intent_signals": {
#             "job_offers": [
#                 {
#                     "title": "Head of Digital Transformation - Insurance Tech",
#                     "department": "Information Technology",
#                     "location": "Nanterre, France",
#                     "posted_date": week_ago.isoformat(),
#                     "description": "Leading digital transformation initiatives across AXA's insurance platforms. Must have experience with AI/ML integration in financial services.",
#                     "seniority": "Director",
#                     "url": "https://jobs.axa.com/digital-transformation-head-123",
#                 },
#                 {
#                     "title": "Senior Data Engineer - Cloud Migration",
#                     "department": "Engineering",
#                     "location": "Nanterre, France",
#                     "posted_date": two_weeks_ago.isoformat(),
#                     "description": "Migrating legacy insurance data systems to cloud infrastructure. Python, SAP, Azure experience required.",
#                     "seniority": "Senior",
#                     "url": "https://jobs.axa.com/data-engineer-456",
#                 },
#                 {
#                     "title": "VP of Customer Experience - Digital Channels",
#                     "department": "Marketing",
#                     "location": "Nanterre, France",
#                     "posted_date": (now - timedelta(days=3)).isoformat(),
#                     "description": "Reimagining customer journey across digital touchpoints. Focus on self-service portals and mobile app engagement.",
#                     "seniority": "VP",
#                     "url": "https://jobs.axa.com/vp-cx-789",
#                 },
#             ],
#             "news": [
#                 {
#                     "headline": "AXA France Announces €200M Investment in AI-Powered Claims Processing",
#                     "published_date": (now - timedelta(days=5)).isoformat(),
#                     "source": "Les Echos",
#                     "url": "https://lesechos.fr/axa-ai-investment-2024",
#                     "summary": "AXA's Nanterre hub will lead the development of AI-driven claims automation, expected to reduce processing time by 60% by 2025.",
#                     "category": "Technology Investment",
#                 },
#                 {
#                     "headline": "AXA Partners with Microsoft for Cloud-First Insurance Platform",
#                     "published_date": week_ago.isoformat(),
#                     "source": "TechCrunch",
#                     "url": "https://techcrunch.com/axa-microsoft-partnership",
#                     "summary": "Strategic partnership announced to migrate AXA's core insurance systems to Azure, with focus on scalability and compliance.",
#                     "category": "Strategic Partnership",
#                 },
#                 {
#                     "headline": "AXA Group Reports 15% YoY Growth in Digital Policy Sales",
#                     "published_date": two_weeks_ago.isoformat(),
#                     "source": "Reuters",
#                     "url": "https://reuters.com/axa-digital-growth-q4",
#                     "summary": "Q4 earnings call highlights acceleration in digital channel adoption, driven by improved mobile app and chatbot experiences.",
#                     "category": "Financial Performance",
#                 },
#             ],
#         },
#     }


# # ── Test Campaign State ────────────────────────────────────────────────────────

# def get_test_campaign_state():
#     """
#     Complete campaign state for testing pipeline through Node 4
#     """
#     return {
#         # ── Input Fields ──────────────────────────────────────────────────
#         "icp_description_text": """
#         Target Profile:
#         - Industry: Insurance, Financial Services
#         - Company Size: 5,000 - 15,000 employees
#         - Geography: France (Ile-de-France region preferred)
#         - Revenue: €10B - €50B annual revenue
#         - Tech Stack: Python, SAP, Microsoft Azure, Salesforce
#         - Target Roles: VP of Digital Transformation, Head of Data, CTO
#         - Exclude: Gambling, Cryptocurrency companies
        
#         Intent Signals:
#         - Recent job postings for digital transformation or cloud migration roles
#         - News about technology investments or partnerships
#         - Active cloud migration projects
#         """,
        
#         "user_offering": """
#         Cloud-native data platform for insurance companies. Accelerates 
#         claims processing with AI/ML, ensures GDPR compliance, and integrates 
#         with existing SAP/Salesforce systems. Typical ROI: 40% cost reduction 
#         in data operations within 12 months.
#         """,
        
#         "blacklist": {
#             "companies": [],  # No blacklist for this test
#             "personas": [],
#         },
        
#         "configurable_weights": {
#             # Firmographic weights
#             "industry_match": 0.30,
#             "company_size_match": 0.20,
#             "revenue_match": 0.15,
#             "tech_stack_match": 0.35,
            
#             # Thresholds
#             "passing_threshold": 50.0,
#             "nurture_threshold": 25.0,
#             "max_km_radius": 50.0,
            
#             # Composite weights
#             "firmographic_weight": 0.60,
#             "intent_weight": 0.40,
#         },
        
#         "campaign_id": "test_campaign_axa_001",
        
#         # ── Sourced Data ──────────────────────────────────────────────────
#         "sourced_companies": [get_test_company_data()],
#         "sourced_personas": [],  # Not needed until Node 5
        
#         # ── State Fields (Will be populated by nodes) ─────────────────────
#         "extracted_icp": None,
#         "filtered_companies": [],
#         "nurture_companies": [],
#         "ranked_companies": [],
#         "ranked_personas": [],
#         "user_approved_companies": None,
#         "pipeline_error": None,
        
#         # ── Disqualification Log (Initialized) ────────────────────────────
#         "disqualification_log": {
#             "total_evaluated": 0,
#             "total_passed": 0,
#             "total_disqualified": 0,
#             "records": [],
#             "summary": {},
#         },
#     }


# # ── Test Runner ────────────────────────────────────────────────────────────────

# def test_pipeline_through_node_4():
#     """
#     Test the pipeline from Node 1 → Node 4
#     """
#     from graph.nodes import (
#         extract_icp_node,
#         normalize_company_data_node,
#         filter_and_gate_node,
#         score_and_rank_node,
#     )
    
#     # Initialize state
#     state = get_test_campaign_state()
    
#     print("=" * 80)
#     print("TESTING STRATEGIC QUALIFIER PIPELINE (Nodes 1-4)")
#     print("=" * 80)
    
#     # ── Node 1: Extract ICP ───────────────────────────────────────────────
#     print("\n[NODE 1] Extracting ICP from campaign brief...")
#     node1_output = extract_icp_node(state)
#     state.update(node1_output)
    
#     if state.get("pipeline_error"):
#         print(f"❌ Pipeline halted: {state['pipeline_error']}")
#         return state
    
#     print("✅ ICP extracted:")
#     icp = state["extracted_icp"]
#     print(f"   - Industries: {icp.must_have.industry}")
#     print(f"   - Size Range: {icp.must_have.company_size.min} - {icp.must_have.company_size.max}")
#     print(f"   - Countries: {icp.must_have.target_countries}")
#     print(f"   - Target Roles: {icp.target_roles}")
    
#     # ── Node 2: Normalize Company Data ────────────────────────────────────
#     print("\n[NODE 2] Normalizing company data...")
#     node2_output = normalize_company_data_node(state)
#     state.update(node2_output)
    
#     normalized_companies = state["sourced_companies"]
#     print(f"✅ Normalized {len(normalized_companies)} companies")
    
#     if normalized_companies:
#         co = normalized_companies[0]
#         print(f"   - Company: {co['name']}")
#         print(f"   - Industry (raw): {co['industry_raw']}")
#         print(f"   - Industry (mapped): {co['mapped_industry']}")
#         print(f"   - Tech Stack: {co['tech_stack'][:5]}...")  # First 5 techs
#         print(f"   - Intent Signals:")
#         print(f"     • Job Offers: {len(co['intent_signals']['job_offers'])}")
#         print(f"     • News: {len(co['intent_signals']['news'])}")
    
#     # ── Node 3: Filter and Gate ───────────────────────────────────────────
#     print("\n[NODE 3] Applying gates and filters...")
#     node3_output = filter_and_gate_node(state)
#     state.update(node3_output)
    
#     filtered = state["filtered_companies"]
#     disq_log = state["disqualification_log"]
    
#     print(f"✅ Gate results:")
#     print(f"   - Evaluated: {disq_log['total_evaluated']}")
#     print(f"   - Passed: {disq_log['total_passed']}")
#     print(f"   - Disqualified: {disq_log['total_disqualified']}")
    
#     if disq_log["summary"]:
#         print(f"   - Disqualification reasons:")
#         for reason, count in disq_log["summary"].items():
#             print(f"     • {reason}: {count}")
    
#     if not filtered:
#         print("❌ No companies survived gates. Test stopped.")
#         return state
    
#     # ── Node 4: Score and Rank ────────────────────────────────────────────
#     print("\n[NODE 4] Scoring and ranking companies...")
#     node4_output = score_and_rank_node(state)
#     state.update(node4_output)
    
#     ranked = state["ranked_companies"]
#     nurture = state["nurture_companies"]
    
#     print(f"✅ Scoring results:")
#     print(f"   - Qualified: {len(ranked)}")
#     print(f"   - Nurture: {len(nurture)}")
    
#     if ranked:
#         print("\n   📊 Top Qualified Company:")
#         top = ranked[0]
#         metrics = top["qualification_metrics"]
#         print(f"   - Name: {top['name']}")
#         print(f"   - Firmographic Score: {metrics['firmographic_score']:.1f}/100")
#         print(f"   - Intent Score: {metrics['intent_score']:.1f}/100")
#         print(f"   - Total Score: {metrics['total_score']:.1f}/100")
#         print(f"   - Tier: {metrics['tier']}")
#         print(f"\n   🧠 Intent Reasoning:")
#         print(f"   {metrics['intent_reasoning'][:200]}...")
        
#         print(f"\n   📈 Firmographic Breakdown:")
#         for signal, score in metrics['breakdown'].items():
#             print(f"     • {signal}: {score}")
    
#     print("\n" + "=" * 80)
#     print("TEST COMPLETE ✓")
#     print("=" * 80)
    
#     return state


# if __name__ == "__main__":
#     final_state = test_pipeline_through_node_4()
    
#     # Optional: Pretty-print final state
#     import json
    
#     print("\n[DEBUG] Final State Keys:")
#     for key in final_state.keys():
#         if key == "ranked_companies" and final_state[key]:
#             print(f"  - {key}: {len(final_state[key])} companies")
#         elif key == "disqualification_log":
#             print(f"  - {key}: {final_state[key]['total_disqualified']} disqualified")
#         elif key not in ["sourced_companies", "extracted_icp"]:
#             print(f"  - {key}: {type(final_state[key]).__name__}")


# qualifier_agent/tests/test_comprehensive.py

"""
Comprehensive Pipeline Stress Test
──────────────────────────────────
Tests all edge cases: gates, geo-filtering, scoring tiers, blacklists,
subsidiary handling, and configurable weights.

Expected Results:
- 15 companies evaluated
- ~6 qualified (Tier A/B)
- ~3 nurture candidates
- ~6 disqualified (gates/geo/blacklist)
"""

from datetime import datetime, timedelta
from typing import Dict, Any, List

import os
import sys

# # Dynamically ensure root directory is accessible for imports
ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)
from graph.state import CampaignState
# ══════════════════════════════════════════════════════════════════════════════
# COMPANY DATA GENERATORS
# ══════════════════════════════════════════════════════════════════════════════

def _base_company(overrides: Dict[str, Any]) -> Dict[str, Any]:
    """Base template for company data"""
    now = datetime.now()
    base = {
        "apollo_id": f"test_{overrides.get('name', 'unknown').lower().replace(' ', '_')}",
        "domain": f"{overrides.get('name', 'unknown').lower().replace(' ', '')}.com",
        "website_url": f"http://{overrides.get('name', 'unknown').lower().replace(' ', '')}.com",
        "industry": "Insurance",
        "estimated_num_employees": 8000,
        "annual_revenue": 25000000000,
        "founded_year": 2000,
        "city": "Paris",
        "country": "France",
        "state": "Ile-de-France",
        "postal_code": "75001",
        "street_address": "1 Rue de Test",
        "raw_address": "1 Rue de Test, Paris, France",
        "latest_funding_stage": "Series C",
        "funding_events": "[]",
        "technologies": '[{"uid": "python", "name": "Python", "category": "Programming"}, {"uid": "sap", "name": "SAP", "category": "ERP"}]',
        "competitors": '[]',
        "departments": '{"sales": 100, "engineering": 50, "marketing": 30}',
        "keywords": '["insurance", "technology"]',
        "full_description": f"{overrides.get('name', 'Test')} is an insurance company.",
        "short_description": "Insurance provider",
        "is_subsidiary": False,
        "parent_company": None,
        "num_suborganizations": 0,
        "suborganizations": "[]",
        "linkedin_url": f"http://linkedin.com/company/{overrides.get('name', 'test')}",
        "twitter_url": None,
        "logo_url": None,
        "data_quality_score": 0.85,
        "alexa_ranking": 50000,
        "phone": "+33 1 23 45 67 89",
        "fiscal_year_end": "December",
        "source": "Test Data",
        "captured_at": now.isoformat(),
        "intent_signals": {
            "job_offers": [],
            "news": [],
        },
    }
    base.update(overrides)
    return base


def get_company_1_perfect_match() -> Dict[str, Any]:
    """AXA France - Perfect Tier A match"""
    now = datetime.now()
    return _base_company({
        "name": "AXA France",
        "apollo_id": "556936c873696421ab590d00",
        "domain": "axa.fr",
        "industry": "Assurance et Services Financiers",
        "estimated_num_employees": 9000,
        "annual_revenue": 31644000000,
        "founded_year": 1971,
        "city": "Nanterre",
        "technologies": '[{"uid": "python", "name": "Python", "category": "Programming"}, {"uid": "sap", "name": "SAP", "category": "ERP"}, {"uid": "azure", "name": "Microsoft Azure", "category": "Cloud"}, {"uid": "salesforce", "name": "Salesforce", "category": "CRM"}]',
        "full_description": "AXA France is a leading insurance and financial services company with cutting-edge digital transformation initiatives, leveraging Python, SAP, Azure, and AI.",
        "intent_signals": {
            "job_offers": [
                {
                    "title": "VP of Digital Transformation",
                    "department": "Technology",
                    "location": "Nanterre, France",
                    "posted_date": (now - timedelta(days=5)).isoformat(),
                    "description": "Lead cloud migration and AI integration projects.",
                    "seniority": "VP",
                },
                {
                    "title": "Head of Data Engineering",
                    "department": "Engineering",
                    "location": "Paris, France",
                    "posted_date": (now - timedelta(days=10)).isoformat(),
                    "description": "Build scalable data pipelines on Azure.",
                    "seniority": "Director",
                },
            ],
            "news": [
                {
                    "headline": "AXA Invests €200M in AI-Powered Claims Processing",
                    "published_date": (now - timedelta(days=7)).isoformat(),
                    "source": "TechCrunch",
                    "summary": "Major digital transformation initiative announced.",
                },
            ],
        },
    })


def get_company_2_geo_challenge() -> Dict[str, Any]:
    """Allianz Germany - Good fit but outside France"""
    now = datetime.now()
    return _base_company({
        "name": "Allianz Germany",
        "apollo_id": "allianz_de_001",
        "domain": "allianz.de",
        "industry": "Insurance",
        "estimated_num_employees": 12000,
        "annual_revenue": 45000000000,
        "city": "Munich",
        "country": "Germany",
        "state": "Bavaria",
        "technologies": '[{"uid": "python", "name": "Python", "category": "Programming"}, {"uid": "aws", "name": "AWS", "category": "Cloud"}]',
        "full_description": "Allianz is a global insurance leader based in Germany.",
        "intent_signals": {
            "job_offers": [
                {
                    "title": "Cloud Architect",
                    "posted_date": (now - timedelta(days=15)).isoformat(),
                },
            ],
            "news": [],
        },
    })


def get_company_3_low_intent() -> Dict[str, Any]:
    """Swiss Life Zurich - Decent firmographic, no intent"""
    return _base_company({
        "name": "Swiss Life Zurich",
        "apollo_id": "swiss_life_ch_001",
        "domain": "swisslife.ch",
        "industry": "Insurance",
        "estimated_num_employees": 7000,
        "annual_revenue": 18000000000,
        "city": "Zurich",
        "country": "Switzerland",
        "state": "Zurich",
        "technologies": '[{"uid": "java", "name": "Java", "category": "Programming"}]',
        "full_description": "Swiss Life is a traditional insurance provider.",
        "intent_signals": {"job_offers": [], "news": []},
    })


def get_company_4_geo_fail() -> Dict[str, Any]:
    """Generali Italy - Outside max_km_radius from France"""
    return _base_company({
        "name": "Generali Italy",
        "apollo_id": "generali_it_001",
        "domain": "generali.it",
        "industry": "Insurance",
        "estimated_num_employees": 10000,
        "annual_revenue": 30000000000,
        "city": "Trieste",
        "country": "Italy",
        "state": "Friuli-Venezia Giulia",
        "technologies": '[{"uid": "python", "name": "Python", "category": "Programming"}]',
        "full_description": "Generali is a major Italian insurance group.",
    })


def get_company_5_too_small() -> Dict[str, Any]:
    """Tiny Insurance Startup - Below size gate"""
    return _base_company({
        "name": "Tiny Insurance Startup",
        "apollo_id": "tiny_startup_001",
        "domain": "tinyinsure.com",
        "industry": "Insurance",
        "estimated_num_employees": 50,  # Below ICP min 5,000
        "annual_revenue": 2000000,
        "city": "Paris",
        "technologies": '[{"uid": "python", "name": "Python", "category": "Programming"}]',
        "full_description": "Early-stage insurtech startup.",
    })


def get_company_6_too_large() -> Dict[str, Any]:
    """MegaCorp Insurance - Above size gate"""
    return _base_company({
        "name": "MegaCorp Insurance",
        "apollo_id": "megacorp_001",
        "domain": "megacorp.com",
        "industry": "Insurance",
        "estimated_num_employees": 50000,  # Above ICP max 15,000
        "annual_revenue": 100000000000,
        "city": "Paris",
        "technologies": '[{"uid": "python", "name": "Python", "category": "Programming"}]',
        "full_description": "Global insurance conglomerate.",
    })


def get_company_7_blacklist() -> Dict[str, Any]:
    """CryptoInsure - On blacklist"""
    return _base_company({
        "name": "CryptoInsure",
        "apollo_id": "cryptoinsure_001",
        "domain": "cryptoinsure.com",
        "industry": "Insurance",
        "estimated_num_employees": 8000,
        "annual_revenue": 20000000000,
        "city": "Paris",
        "full_description": "Insurance for cryptocurrency assets.",
    })


def get_company_8_excluded_industry() -> Dict[str, Any]:
    """Gambling Insurance Co - Excluded industry"""
    return _base_company({
        "name": "Gambling Insurance Co",
        "apollo_id": "gambling_ins_001",
        "domain": "gamblinginsure.com",
        "industry": "Gambling",  # Excluded in ICP
        "estimated_num_employees": 7000,
        "annual_revenue": 15000000000,
        "city": "Paris",
        "full_description": "Insurance products for gambling operators.",
    })


def get_company_9_excluded_keyword() -> Dict[str, Any]:
    """Casino Protection Services - Banned keyword in description"""
    return _base_company({
        "name": "Casino Protection Services",
        "apollo_id": "casino_protect_001",
        "domain": "casinoprotect.com",
        "industry": "Insurance",
        "estimated_num_employees": 6000,
        "annual_revenue": 12000000000,
        "city": "Paris",
        "keywords": '["casino", "gaming", "protection"]',
        "full_description": "We provide insurance and protection services for casino operators and gaming facilities.",
    })


def get_company_10_financial_perfect() -> Dict[str, Any]:
    """BNP Paribas - Financial Services, perfect tech match"""
    now = datetime.now()
    return _base_company({
        "name": "BNP Paribas",
        "apollo_id": "bnp_paribas_001",
        "domain": "bnpparibas.com",
        "industry": "Financial Services",
        "estimated_num_employees": 11000,
        "annual_revenue": 42000000000,
        "city": "Paris",
        "technologies": '[{"uid": "python", "name": "Python", "category": "Programming"}, {"uid": "sap", "name": "SAP", "category": "ERP"}, {"uid": "azure", "name": "Microsoft Azure", "category": "Cloud"}, {"uid": "salesforce", "name": "Salesforce", "category": "CRM"}]',
        "full_description": "BNP Paribas is a leading European bank with advanced digital banking platforms.",
        "intent_signals": {
            "job_offers": [
                {
                    "title": "Chief Technology Officer",
                    "posted_date": (now - timedelta(days=3)).isoformat(),
                },
            ],
            "news": [
                {
                    "headline": "BNP Paribas Launches Cloud-Native Banking Platform",
                    "published_date": (now - timedelta(days=5)).isoformat(),
                },
            ],
        },
    })


def get_company_11_medium_intent() -> Dict[str, Any]:
    """Société Générale - Good match, lower intent"""
    now = datetime.now()
    return _base_company({
        "name": "Société Générale",
        "apollo_id": "socgen_001",
        "domain": "socgen.com",
        "industry": "Financial Services",
        "estimated_num_employees": 9500,
        "annual_revenue": 35000000000,
        "city": "Paris",
        "technologies": '[{"uid": "python", "name": "Python", "category": "Programming"}, {"uid": "oracle", "name": "Oracle", "category": "Database"}]',
        "full_description": "Société Générale is a major French bank.",
        "intent_signals": {
            "job_offers": [],
            "news": [
                {
                    "headline": "Société Générale Q4 Earnings Beat Expectations",
                    "published_date": (now - timedelta(days=30)).isoformat(),
                },
            ],
        },
    })


def get_company_12_low_tech_overlap() -> Dict[str, Any]:
    """Crédit Agricole - Low tech stack overlap"""
    return _base_company({
        "name": "Crédit Agricole",
        "apollo_id": "credit_agricole_001",
        "domain": "credit-agricole.fr",
        "industry": "Financial Services",
        "estimated_num_employees": 8500,
        "annual_revenue": 28000000000,
        "city": "Paris",
        "technologies": '[{"uid": "java", "name": "Java", "category": "Programming"}, {"uid": "oracle", "name": "Oracle", "category": "Database"}]',
        "full_description": "Crédit Agricole is a cooperative banking group.",
    })


def get_company_13_revenue_fail() -> Dict[str, Any]:
    """LCL - Revenue below ICP minimum"""
    return _base_company({
        "name": "LCL (Le Crédit Lyonnais)",
        "apollo_id": "lcl_001",
        "domain": "lcl.fr",
        "industry": "Financial Services",
        "estimated_num_employees": 7000,
        "annual_revenue": 2000000000,  # Below ICP min €10B
        "city": "Lyon",
        "country": "France",
        "state": "Auvergne-Rhône-Alpes",
        "technologies": '[{"uid": "python", "name": "Python", "category": "Programming"}]',
        "full_description": "LCL is a French retail banking network.",
    })


def get_company_14_subsidiary() -> Dict[str, Any]:
    """Groupama - Subsidiary test, medium intent"""
    now = datetime.now()
    return _base_company({
        "name": "Groupama",
        "apollo_id": "groupama_001",
        "domain": "groupama.fr",
        "industry": "Insurance",
        "estimated_num_employees": 8200,
        "annual_revenue": 22000000000,
        "city": "Paris",
        "is_subsidiary": True,
        "parent_company": "Groupama Holding",
        "technologies": '[{"uid": "python", "name": "Python", "category": "Programming"}, {"uid": "sap", "name": "SAP", "category": "ERP"}]',
        "full_description": "Groupama is a mutual insurance group.",
        "intent_signals": {
            "news": [
                {
                    "headline": "Groupama Expands Digital Services",
                    "published_date": (now - timedelta(days=20)).isoformat(),
                },
            ],
        },
    })


def get_company_15_old_tech() -> Dict[str, Any]:
    """MAIF - Older tech stack, low intent"""
    return _base_company({
        "name": "MAIF",
        "apollo_id": "maif_001",
        "domain": "maif.fr",
        "industry": "Insurance",
        "estimated_num_employees": 6500,
        "annual_revenue": 16000000000,
        "city": "Niort",
        "country": "France",
        "state": "Nouvelle-Aquitaine",
        "technologies": '[{"uid": "cobol", "name": "COBOL", "category": "Legacy"}, {"uid": "mainframe", "name": "Mainframe", "category": "Legacy"}]',
        "full_description": "MAIF is a mutual insurance company serving individuals.",
    })


# ══════════════════════════════════════════════════════════════════════════════
# TEST CAMPAIGN STATE
# ══════════════════════════════════════════════════════════════════════════════

def get_stress_test_state():
    """
    Campaign state with 15 diverse companies + strict blacklist + custom weights
    """
    return {
        # ── ICP Definition ────────────────────────────────────────────────
        "icp_description_text": """
        Target Profile:
        - Industry: Insurance, Financial Services
        - Company Size: 5,000 - 15,000 employees
        - Geography: France (Ile-de-France region preferred, max 200km radius)
        - Revenue: €10B - €50B annual revenue
        - Tech Stack: Python, SAP, Microsoft Azure, Salesforce
        - Target Roles: VP of Digital Transformation, Head of Data, CTO
        
        Exclusions:
        - Industries: Gambling, Cryptocurrency
        - Keywords: casino, betting, crypto
        - Company Size: 0-100 employees (too small)
        """,
        
        "user_offering": """
        Enterprise cloud-native data platform for financial services. 
        Accelerates claims/transaction processing with AI/ML, ensures 
        regulatory compliance, and integrates with SAP/Salesforce. 
        Typical ROI: 40% cost reduction in 12 months.
        """,
        
        # ── Blacklist (Strict) ────────────────────────────────────────────
        "blacklist": {
            "companies": ["CryptoInsure", "Gambling Insurance"],
            "personas": ["recruiter", "hr assistant"],
        },
        
        # ── Custom Weights (Aggressive Tech Stack Weight) ─────────────────
        "configurable_weights": {
            # Thresholds
            "passing_threshold": 55.0,      # Raised from 50 (stricter)
            "nurture_threshold": 30.0,      # Raised from 25 (stricter)
            "max_km_radius": 200.0,         # Expanded from 50km
            
            # Composite weights
            "firmographic_weight": 0.65,    # Raised (firm fit matters more)
            "intent_weight": 0.35,          # Lowered (compensate)
        },
        
        "campaign_id": "stress_test_001",
        
        # ── All 15 Companies ──────────────────────────────────────────────
        "sourced_companies": [
            get_company_1_perfect_match(),       # AXA France
            get_company_2_geo_challenge(),       # Allianz Germany
            get_company_3_low_intent(),          # Swiss Life Zurich
            get_company_4_geo_fail(),            # Generali Italy
            get_company_5_too_small(),           # Tiny Startup
            get_company_6_too_large(),           # MegaCorp
            get_company_7_blacklist(),           # CryptoInsure
            get_company_8_excluded_industry(),   # Gambling Insurance
            get_company_9_excluded_keyword(),    # Casino Protection
            get_company_10_financial_perfect(),  # BNP Paribas
            get_company_11_medium_intent(),      # Société Générale
            get_company_12_low_tech_overlap(),   # Crédit Agricole
            get_company_13_revenue_fail(),       # LCL
            get_company_14_subsidiary(),         # Groupama
            get_company_15_old_tech(),           # MAIF
        ],
        
        "sourced_personas": [],
        
        # ── State Fields ──────────────────────────────────────────────────
        "extracted_icp": None,
        "filtered_companies": [],
        "nurture_companies": [],
        "ranked_companies": [],
        "ranked_personas": [],
        "user_approved_companies": None,
        "pipeline_error": None,
        
        "disqualification_log": {
            "total_evaluated": 0,
            "total_passed": 0,
            "total_disqualified": 0,
            "records": [],
            "summary": {},
        },
    }


# ══════════════════════════════════════════════════════════════════════════════
# TEST RUNNER
# ══════════════════════════════════════════════════════════════════════════════

def run_stress_test():
    """
    Execute comprehensive pipeline stress test
    """
    from graph.nodes import (
        extract_icp_node,
        normalize_company_data_node,
        filter_and_gate_node,
        score_and_rank_node,
    )
    
    state = get_stress_test_state()
    
    print("=" * 100)
    print("STRATEGIC QUALIFIER PIPELINE — COMPREHENSIVE STRESS TEST")
    print("=" * 100)
    print(f"📊 Test Scope: {len(state['sourced_companies'])} companies")
    print(f"🎯 Passing Threshold: {state['configurable_weights']['passing_threshold']}")
    print(f"⚠️  Nurture Threshold: {state['configurable_weights']['nurture_threshold']}")
    print(f"📍 Max Geo Radius: {state['configurable_weights']['max_km_radius']}km")
    print(f"🚫 Blacklist: {state['blacklist']['companies']}")
    print("=" * 100)
    
    # ── Node 1: ICP Extraction ────────────────────────────────────────────
    print("\n[NODE 1] Extracting ICP...")
    state.update(extract_icp_node(state))
    
    if state.get("pipeline_error"):
        print(f"❌ FATAL: {state['pipeline_error']}")
        return state
    
    icp = state["extracted_icp"]
    print(f"✅ Industries: {icp.must_have.industry}")
    print(f"✅ Size: {icp.must_have.company_size.min}-{icp.must_have.company_size.max}")
    print(f"✅ Exclude Industries: {icp.exclude.industries if icp.exclude else []}")
    print(f"✅ Exclude Keywords: {icp.exclude.keywords if icp.exclude else []}")
    
    # ── Node 2: Normalization ─────────────────────────────────────────────
    print("\n[NODE 2] Normalizing company data...")
    state.update(normalize_company_data_node(state))
    print(f"✅ Normalized: {len(state['sourced_companies'])} companies")
    
    # ── Node 3: Gates & Filters ───────────────────────────────────────────
    print("\n[NODE 3] Applying defensive gates...")
    state.update(filter_and_gate_node(state))
    
    disq_log = state["disqualification_log"]
    print(f"✅ Evaluated: {disq_log['total_evaluated']}")
    print(f"✅ Passed Gates: {disq_log['total_passed']}")
    print(f"❌ Disqualified: {disq_log['total_disqualified']}")
    
    if disq_log["summary"]:
        print("\n📋 Disqualification Breakdown:")
        for reason, count in sorted(disq_log["summary"].items(), key=lambda x: -x[1]):
            print(f"   • {reason}: {count}")
    
    # Show who got rejected
    print("\n🚫 Rejected Companies:")
    for rec in disq_log["records"]:
        print(f"   • {rec['entity_name']}: {rec['reason_code']}")
    
    # ── Node 4: Scoring & Ranking ─────────────────────────────────────────
    print("\n[NODE 4] Scoring and ranking...")
    state.update(score_and_rank_node(state))
    
    ranked = state["ranked_companies"]
    nurture = state["nurture_companies"]
    
    print(f"✅ Qualified: {len(ranked)}")
    print(f"⚠️  Nurture: {len(nurture)}")
    
    # ── Results Tables ────────────────────────────────────────────────────
    if ranked:
        print("\n" + "=" * 100)
        print("🏆 QUALIFIED COMPANIES (Tier A/B)")
        print("=" * 100)
        print(f"{'Rank':<5} {'Company':<30} {'Firm':<7} {'Intent':<7} {'Total':<7} {'Tier':<5}")
        print("-" * 100)
        
        for i, co in enumerate(ranked, 1):
            m = co["qualification_metrics"]
            print(f"{i:<5} {co['name']:<30} {m['firmographic_score']:>6.1f} {m['intent_score']:>6.1f} {m['total_score']:>6.1f} {m['tier']:<5}")
    
    if nurture:
        print("\n" + "=" * 100)
        print("⏳ NURTURE BUCKET (Future Potential)")
        print("=" * 100)
        print(f"{'Company':<30} {'Firm Score':<12} {'Reason':<50}")
        print("-" * 100)
        
        for co in nurture:
            m = co["qualification_metrics"]
            print(f"{co['name']:<30} {m['firmographic_score']:>11.1f} {'Low intent / tech mismatch':<50}")
    
    # ── Final Statistics ──────────────────────────────────────────────────
    print("\n" + "=" * 100)
    print("📈 PIPELINE STATISTICS")
    print("=" * 100)
    
    total = disq_log["total_evaluated"]
    qualified = len(ranked)
    nurture_count = len(nurture)
    disqualified = disq_log["total_disqualified"]
    
    print(f"Total Companies Evaluated:  {total}")
    print(f"├─ ✅ Qualified (Tier A/B): {qualified} ({qualified/total*100:.1f}%)")
    print(f"├─ ⏳ Nurture Bucket:        {nurture_count} ({nurture_count/total*100:.1f}%)")
    print(f"└─ ❌ Disqualified:          {disqualified} ({disqualified/total*100:.1f}%)")
    
    print("\n🎯 Conversion Funnel:")
    print(f"   Input → Node 2:  {total} companies")
    print(f"   Node 2 → Node 3: {disq_log['total_passed']} (gates passed)")
    print(f"   Node 3 → Node 4: {len(state['sourced_companies'])} (geo filtered)")
    print(f"   Node 4 Output:   {qualified} qualified + {nurture_count} nurture")
    
    # ── Detailed Breakdown for Top 3 ──────────────────────────────────────
    if ranked:
        print("\n" + "=" * 100)
        print("🔍 DETAILED BREAKDOWN (Top 3)")
        print("=" * 100)
        
        for i, co in enumerate(ranked[:3], 1):
            m = co["qualification_metrics"]
            print(f"\n[{i}] {co['name']}")
            print(f"    Total Score: {m['total_score']}/100 (Tier {m['tier']})")
            print(f"    ├─ Firmographic: {m['firmographic_score']}/100")
            
            if "breakdown" in m:
                for signal, details in m["breakdown"].items():
                    if isinstance(details, dict):
                        score = details.get("score", 0)
                        quality = details.get("match_quality", "unknown")
                        print(f"    │  ├─ {signal}: {score}/100 ({quality})")
                    else:
                        print(f"    │  ├─ {signal}: {details}")
            
            print(f"    └─ Intent: {m['intent_score']}/100")
            
            if m.get("intent_reasoning"):
                reasoning = m["intent_reasoning"][:150]
                print(f"       Reasoning: {reasoning}...")
    
    print("\n" + "=" * 100)
    print("✅ STRESS TEST COMPLETE")
    print("=" * 100)
    
    return state


if __name__ == "__main__":
    run_stress_test()