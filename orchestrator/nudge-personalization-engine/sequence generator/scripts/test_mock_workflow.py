"""
Test full sequence generator workflow in mock mode.
This skips Hunter/Tavily API calls and uses mock data.
"""
import os
import sys

# Enable mock mode for testing
os.environ["DEBUG_MCP_TESTING"] = "true"

from graph_engine import app as agent_workflow

def test_workflow():
    print("=" * 60)
    print("TESTING SEQUENCE GENERATOR - MOCK MODE")
    print("=" * 60)
    
    # Test with a sample domain
    test_domain = "gomycode.com"
    
    print(f"\n[1] Starting workflow for: {test_domain}")
    print("-" * 60)
    
    # Initial state
    state = {
        "entreprise": test_domain,
        "contact_info": {},
        "contexte_web": {},
        "strategie_finale": "",
        "message_genere": None
    }
    
    print("[2] Running LangGraph workflow...")
    print("    Steps: Hunter (mock) → Tavily (mock) → Gemini → Message Generator")
    print("-" * 60)
    
    try:
        # Run the workflow
        final_state = agent_workflow.invoke(state)
        
        # Display results
        print("\n[✓] WORKFLOW COMPLETED")
        print("=" * 60)
        
        # Contact info
        contact = final_state.get('contact_info', {})
        print(f"\n📋 CONTACT INFO (Mock):")
        print(f"    Name: {contact.get('nom', 'N/A')}")
        print(f"    Email: {contact.get('email', 'N/A')}")
        print(f"    Title: {contact.get('titre', 'N/A')}")
        print(f"    Company: {contact.get('entreprise', 'N/A')}")
        
        # Web context
        contexte = final_state.get('contexte_web', {})
        print(f"\n🌐 WEB CONTEXT (Mock):")
        print(f"    {contexte.get('profil_brut', 'N/A')[:100]}...")
        
        # Strategy
        strategie = final_state.get('strategie_finale', '')
        print(f"\n🧠 STRATEGY (Gemini):")
        if strategie:
            print(f"    {strategie[:200]}...")
        else:
            print("    [No strategy generated - check GOOGLE_API_KEY]")
        
        # Generated message
        message_data = final_state.get('message_genere', {})
        print(f"\n✉️  GENERATED MESSAGE:")
        print("-" * 60)
        if message_data:
            print(f"    Success: {message_data.get('success')}")
            print(f"    Score: {message_data.get('score')}")
            if message_data.get('success'):
                print(f"\n    Subject: {message_data.get('subject', 'N/A')}")
                print(f"\n    Message:")
                print(f"    {message_data.get('message', 'N/A')[:300]}...")
            else:
                print(f"    Error: {message_data.get('error')}")
        else:
            print("    [No message generated]")
        
        print("\n" + "=" * 60)
        print("[✓] Mock workflow test complete!")
        print("=" * 60)
        
    except Exception as e:
        print(f"\n[✗] WORKFLOW FAILED: {str(e)}")
        import traceback
        traceback.print_exc()
        return False
    
    return True

if __name__ == "__main__":
    success = test_workflow()
    sys.exit(0 if success else 1)
