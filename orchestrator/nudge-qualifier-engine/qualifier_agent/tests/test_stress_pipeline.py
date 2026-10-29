import os
import sys
import json

# Ensure root directory is accessible
ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from graph.nodes import extract_icp_node, normalize_company_data_node, filter_and_gate_node

# 1. Broad Strict ICP Rules Setup
RAW_CAMPAIGN_TEXT = """
Targeting high-growth tech firms in SaaS and FinTech. 
Exclude anything related to Tobacco or Gambling.
Absolutely drop small shops or freelancers with 0 to 9 employees.
"""

# 2. Complete Chaos Data Payload
CHAOS_SOURCED_COMPANIES = [
    {
        # CASE A: The Destroyed Tech String & String Float Headcount
        "name": "Chaos Engineering Corp",
        "apollo_id": ["this-should-not-be-an-array-but-must-not-crash-us"], 
        "industry": "SaaS",
        "estimated_num_employees": "1250.85", # Float as a string! Tests casting logic.
        "annual_revenue": "non renseigné",    # French placeholder test.
        # Deeply broken serialized JSON with missing brackets/quotes to trigger Regex Recovery
        "technologies": '{uid:"broken-id", name:"Python", category:"Language"} {uid:"aws-id", name:"AWS"}',
        "full_description": "Clean tech firm building automated payment routers.",
        "short_description": "Fintech tools.",
    },
    {
        # CASE B: Deeply Hidden Industry Bomb
        "name": "Vape Cloud Tech",
        "industry": "Software Innovation", # Masked industry label to bypass regular checks
        "estimated_num_employees": "500",
        # Hiding a banned domain word ("Tobacco") deep in the text body
        "full_description": "We are a top tier platform optimizing global logistics supply chains for traditional commercial fields including TOBACCO distributors and agricultural conglomerates.",
        "short_description": "Logistics app.",
    },
    {
        # CASE C: Total Null/Missing Data Nightmare
        "name": "Empty Shell Ltd",
        "apollo_id": "",
        "industry": "unknown",
        "estimated_num_employees": None, # Missing completely
        "technologies": "none",
        "full_description": "",
        "short_description": "N/A",
    }
]

def run_stress_test():
    print("☣️  INITIALIZING PIPELINE COMPLIANCE & BLACKLIST STRESS TEST MATRIX")
    print("=" * 90)
    
    # UPDATED: "Chaos Engineering Corp" is now added to the dynamic blacklist array
    state = {
        "icp_description_text": RAW_CAMPAIGN_TEXT,
        "sourced_companies": CHAOS_SOURCED_COMPANIES,
        "blacklist": {"companies": ["Chaos Engineering Corp"], "personas": []},
        "pipeline_error": None,
        "disqualification_log": {
            "total_evaluated": 0, "total_passed": 0, "total_disqualified": 0,
            "records": [], "summary": {},
        },
    }

    # Execute Node 1
    print("\n💥 [STAGE 1] Parsing ICP Rules...")
    result_1 = extract_icp_node(state)
    state.update(result_1)

    # Check circuit breaker
    if state.get("pipeline_error"):
        print(f"PIPELINE HALTED: {state['pipeline_error']}")
        return
    
    # Execute Node 2
    print("\n💥 [STAGE 2] Running Toxic Normalization Batch...")
    result_2 = normalize_company_data_node(state)
    state.update(result_2)
    
    # Execute Node 3
    print("\n💥 [STAGE 3] Running Gating Logic Over Normalized Chaos Output...")
    result_3 = filter_and_gate_node(state)
    state.update(result_3)
    
    final_cleared = state.get("sourced_companies", [])
    disqualifications_log = state.get("disqualification_log", {})
    disqualifications = disqualifications_log.get("records", []) if isinstance(disqualifications_log, dict) else []

    print("\n" + "═"*90)
    print("📊 STRESS TEST STRUCTURAL AUDIT REPORT")
    print("═"*90)

    # Inspect Chaos Engineering Corp Recovery Metrics if it somehow survived
    chaos_co = next((c for c in final_cleared if "Chaos" in c["name"]), None)
    print("🛠️  RECOVERY ANALYSIS (Chaos Engineering Corp):")
    if chaos_co:
        print(f"  • Headcount Type Coercion Result : {type(chaos_co['estimated_num_employees'])} (Value: {chaos_co['estimated_num_employees']})")
        print(f"  • French Placeholder Cleared    : {chaos_co['annual_revenue'] is None} (Value: {chaos_co['annual_revenue']})")
        print(f"  • Regex Tech Recovery Output    : {chaos_co['tech_stack']}")
    else:
        print("  ✅ Chaos Engineering Corp was successfully blocked by the gate filters (Expected behavior).")

    print(f"\n🟢 SURVIVED PIPELINE GATES ({len(final_cleared)}):")
    if final_cleared:
        for c in final_cleared:
            print(f"  • {c['name']} | Headcount: {c['estimated_num_employees']} | Tech: {c['tech_stack']}")
    else:
        print("  (None)")

    print(f"\n🔴 DETECTED AND DROPPED SAFELY ({len(disqualifications)}):")
    for log in disqualifications:
        print(f"  \u2022 Company : {log.get('entity_name', log.get('company_name', '?'))}\n    Reason  : {log.get('reason_detail', log.get('reason', '?'))}\n")
    print("═"*90 + "\n")

if __name__ == "__main__":
    run_stress_test()