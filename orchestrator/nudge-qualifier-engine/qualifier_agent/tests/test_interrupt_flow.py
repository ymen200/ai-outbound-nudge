"""
test_interrupt_flow.py
───────────────────────
Step 3 test: confirm the real pipeline pauses at rank_personas_node and
can be resumed with an approval list using modern LangGraph State History.
"""

import os
import sys

# Dynamically ensure root directory is accessible for imports
ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from langgraph.types import Command
from graph.workflow import get_pipeline
from mock_companies import MOCK_COMPANIES

# ── Define the Test Payload ─────────────────────────────────────────────
test_input = {
    "icp_description_text": (
        "We sell AI-powered fraud-detection and risk-scoring software to mid-size "
        "insurance and financial services companies in France and Germany, "
        "targeting businesses with 100 to 2000 employees."
    ),
    "user_offering": "AI-powered fraud detection software for insurers.",
    "blacklist": {
        "companies": [], 
        "personas": [],
        "industries": ["Gambling", "Casinos", "Betting"]
    },
    "configurable_weights": {
        "target_role_match": 0.50
    },
    "campaign_id": "test-campaign-001",
    "sourced_companies": MOCK_COMPANIES,
    "sourced_personas": [],
}

config = {"configurable": {"thread_id": "test-campaign-001"}}


def run_first_call():
    print("=" * 60)
    print("CALL 1: Running pipeline (Nodes 1-4, then pause at Node 5)")
    print("=" * 60)

    # 1. Run the graph initialization pass
    # When it hits an interrupt, it updates the checkpointer state and stops
    pipeline = get_pipeline()
    pipeline.invoke(test_input, config=config)

    # 2. Inspect the thread checkpoint state to find the interrupt payload
    state_snapshot = pipeline.get_state(config)
    
    # Check if there are any active tasks waiting on human interaction
    if state_snapshot.tasks:
        # Extract the interrupt payload from the active tasks
        interrupts = state_snapshot.tasks[0].interrupts
        if interrupts:
            interrupt_data = interrupts[0].value
            print("\n>>> Pipeline PAUSED as expected.")
            print(">>> Interrupt payload received (Companies pending approval):")
            
            # Print layout summary
            companies = interrupt_data.get("companies", []) if isinstance(interrupt_data, dict) else interrupt_data
            for c in companies:
                name = c.get("name", "Unknown")
                score = c.get("company_score", 0.0)
                print(f"    - {name} (Score: {score})")
                
            return interrupt_data

    print("\n>>> Pipeline did NOT pause — it ran to completion.")
    print(">>> Final State Snapshot Keys:", state_snapshot.values.keys())
    return None


def run_second_call(interrupt_data):
    print("\n" + "=" * 60)
    print("CALL 2: Resuming with a simulated human approval list")
    print("=" * 60)

    # If interrupt data was wrapped or direct, ensure list form
    companies = interrupt_data.get("companies", []) if isinstance(interrupt_data, dict) else interrupt_data
    if not companies:
        print(">>> No companies in the interrupt payload — nothing to approve.")
        return

    # Simulate human choice: Select the first approved entity target
    approved_ids = [
        c.get("apollo_id") or c.get("domain")
        for c in companies[:1]
        if c.get("apollo_id") or c.get("domain")
    ]
    
    print(f">>> User clicked 'Approve' on: {approved_ids}")
    print(f">>> Resuming pipeline execution via Command layer...")

    # 3. Resume the workflow stream by passing Command into invoke with NONE as input
    pipeline = get_pipeline()
    final_state = pipeline.invoke(Command(resume=approved_ids), config=config)

    print("\n>>> Final result after resume:")
    final_companies = final_state.get("sourced_companies", [])
    print(f">>> Downstream pipeline processed {len(final_companies)} approved companies.")
    
    for c in final_companies:
        print(f"    - {c.get('name')}: Ranked target leads count = {len(c.get('ranked_target_leads', []))}")


if __name__ == "__main__":
    pending_interrupt_data = run_first_call()
    
    if pending_interrupt_data is not None:
        run_second_call(pending_interrupt_data)