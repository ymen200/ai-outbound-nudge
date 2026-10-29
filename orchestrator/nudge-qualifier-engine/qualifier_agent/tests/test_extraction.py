import os
import sys
import json

# 1. Ensure the root directory is on the system path for clean imports
ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from graph.nodes import extract_icp_node

# 2. Rich, exhaustive prompt covering every schema attribute 
MAXIMAL_ICP_TEXT = """
We want to run a highly targeted campaign. 


Our target companies must be within the FinTech, SaaS, or Logistics sectors.
They must have a minimum headcount size of 100 employees, but no more than 10,000 employees.
Geographically, they must be located within Europe or North America, specifically headquartered in France or Germany.


We prefer companies with an annual revenue / ARR band between €5M and €80M (€5,000,000 to €80,000,000).
We are looking for companies with regional offices located right in Paris, France or Berlin, Germany.
In terms of maturity, they should be in an active growth stage, ideally classified as a Series B company.
Their tech stack should leverage Python and AWS, and it is absolutely required that they use Snowflake.


Exclude all industries related to Gambling or Tobacco.
Immediately reject any companies that match keywords like 'agency', 'non-profit', or 'freelancer' in their profiles.
Never include micro-businesses; explicitly exclude companies with a size range between 0 and 9 employees.

TARGET BUYING PERSONAS:
Uncover decision-maker records matching the following job titles: VP of Sales, Head of Partnerships, and CTO.
"""

def run_maximal_extraction_test():
    print("🚀 Initializing Full-Feature Node 1 (ICP Extraction) Test...")
    
    mock_state = {
        "icp_description_text": MAXIMAL_ICP_TEXT
    }
    
    # Run node
    output_state = extract_icp_node(mock_state)
    icp_object = output_state.get("extracted_icp")
    
    if not icp_object:
        print("❌ Error: Extraction node returned None. Verify your model connection.")
        return

    print("\n" + "═"*70)
    print("🎯 FULL SCHEMA FEATURE DETECTION BREAKDOWN")
    print("═"*70)

    # ─── LAYER 1: MUST HAVE TRAITS ──────────────────────────────────────────
    print("\n🛑 LAYER 1: MustHaveTraits (Hard Filters)")
    print(f"  • industries         : {icp_object.must_have.industry}")
    print(f"  • company_size (Min) : {icp_object.must_have.company_size.min}")
    print(f"  • company_size (Max) : {icp_object.must_have.company_size.max}")
    print(f"  • target_continents  : {icp_object.must_have.target_continents}")
    print(f"  • target_countries   : {icp_object.must_have.target_countries}")

    # ─── LAYER 2: NICE TO HAVE TRAITS ───────────────────────────────────────
    print("\n✨ LAYER 2: NiceToHaveTraits (Soft Ranking Signals)")
    print(f"  • revenue_range (Min): {icp_object.nice_to_have.revenue_range.min}")
    print(f"  • revenue_range (Max): {icp_object.nice_to_have.revenue_range.max}")
    
    print("  • target_cities      :")
    if icp_object.nice_to_have.target_cities:
        for idx, city_ctx in enumerate(icp_object.nice_to_have.target_cities, 1):
            print(f"      [{idx}] City: {city_ctx.city:<10} | Country: {city_ctx.country:<10} | Continent: {city_ctx.continent}")
    else:
        print("      []")
        
    print(f"  • tech_stack         : {icp_object.nice_to_have.tech_stack}")
    print(f"  • growth_stage       : {repr(icp_object.nice_to_have.growth_stage)}")
    print(f"  • funding_stage      : {repr(icp_object.nice_to_have.funding_stage)}")

    # ─── LAYER 3: EXCLUDE CRITERIA ──────────────────────────────────────────
    print("\n🚫 LAYER 3: ExcludeCriteria (Immediate Disqualification)")
    print(f"  • industries         : {icp_object.exclude.industries}")
    print(f"  • keywords           : {icp_object.exclude.keywords}")
    
    if icp_object.exclude.company_size:
        print(f"  • company_size (Min) : {icp_object.exclude.company_size.min}")
        print(f"  • company_size (Max) : {icp_object.exclude.company_size.max}")
    else:
        print("  • company_size       : None")

    # ─── TOP LEVEL BUYING PERSONAS ──────────────────────────────────────────
    print("\n👥 DOWNSTREAM PERSONA CONFIGURATION")
    print(f"  • target_roles       : {icp_object.target_roles}")
    
    # ─── BACKWARDS-COMPATIBILITY VERIFICATION ───────────────────────────────
    print("\n🔄 BACKWARDS-COMPATIBILITY ALIAS CHECK")
    print(f"  • property .industry          : {icp_object.industry}")
    print(f"  • property .target_cities     : {[c.city for c in icp_object.target_cities]}")
    print(f"  • property .tech_stack         : {icp_object.tech_stack}")
    print("═"*70 + "\n")

if __name__ == "__main__":
    run_maximal_extraction_test()