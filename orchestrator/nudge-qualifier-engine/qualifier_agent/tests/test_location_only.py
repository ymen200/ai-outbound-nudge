import os
import sys
import logging

# Ensure root directory is accessible
ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

# Set up logging to display your agent's execution steps in the terminal
logging.basicConfig(level=logging.DEBUG, format="%(levelname)s - %(message)s")
from geo.location_agent import LocationAgent
# Importing the exact classes matching your brain/schemas.py file
from brain.schemas import ICPAttributes, MustHaveTraits, NiceToHaveTraits, CityContext

# 1. Define Target Rules using your exact Pydantic schema architecture
TARGET_ICP = ICPAttributes(
    must_have=MustHaveTraits(
        target_countries=["France"],
        target_continents=["Europe"],
        industry=[]
    ),
    nice_to_have=NiceToHaveTraits(
        target_cities=[
            CityContext(city="Paris", country="France", continent="Europe")
        ]
    )
)

# 2. Raw Input Dataset for spatial filtering checks
MOCK_INPUT_COMPANIES = [
    {
        "name": "AXA France (Paris Office)",
        "apollo_id": "axa-fr",
        "country": "France",
        "city": "Paris",
        "continent": "Europe",
    },
    {
        "name": "Remote Tech Inc (Lyon Office)",
        "apollo_id": "remote-tech",
        "country": "France",
        "city": "Lyon",        # Located too far away from the Paris target radius
        "continent": "Europe",
    },
    {
        "name": "La Boulangerie (No City Data)",
        "apollo_id": "boulangerie-missing",
        "country": "France",
        "city": None,          # Missing city data triggers destination geocode fallback
        "continent": "Europe",
    }
]

def run_isolated_geo_test():
    print("🌍 INITIALIZING ISOLATED GEOSPATIAL FILTER RUN")
    print("=" * 80)
    
    # Instantiate your location agent
    agent = LocationAgent()
    
    # We execute the filters over the mock data with a 30.0 km radius limitation
    max_radius_km = 30.0
    print(f"⚙️  Executing filter_companies() with max_km = {max_radius_km}...\n")
    
    surviving_companies = agent.filter_companies(
        icp=TARGET_ICP,
        db=MOCK_INPUT_COMPANIES,
        max_km=max_radius_km,
        debug=True
    )
    
    print("\n" + "═"*80)
    print("📊 LOCATION AGENT OUTPUT METRICS")
    print("═"*80)
    
    print(f"🟢 PASSED SPATIAL GATES ({len(surviving_companies)}):")
    for co in surviving_companies:
        dist_info = f"{co.get('dist')} km" if co.get('dist') is not None else "None (Fallback)"
        fallback_reason = f" | Fallback Strategy: {co.get('geo_fallback')}" if co.get('geo_fallback') else ""
        print(f"  • {co['name']} | City: {co['city']} | Distance: {dist_info}{fallback_reason}")
        
    # Isolate targets that were dropped
    survivor_names = {c["name"] for c in surviving_companies}
    dropped_companies = [c for c in MOCK_INPUT_COMPANIES if c["name"] not in survivor_names]
    
    print(f"\n🔴 PRUNED / REMOVED BY AGENT ({len(dropped_companies)}):")
    for co in dropped_companies:
        print(f"  • {co['name']} | City: {co['city']} (Outside range threshold or criteria drop)")
    print("═"*80 + "\n")

if __name__ == "__main__":
    run_isolated_geo_test()