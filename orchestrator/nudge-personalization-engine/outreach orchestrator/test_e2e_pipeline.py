"""
Live end-to-end pipeline test through the Outreach Orchestrator.
Tests: Orchestrator → Sequence Generator → Message Generator → Observability
"""
import json
import urllib.request
import time

ORCHESTRATOR_URL = "http://localhost:8002"

# Test payload
payload = {
    "lead_id": "test-e2e-001",
    "campaign_id": "e2e_test_campaign",
    "entreprise": "TechCorp Solutions",
    "contact_info": {
        "full_name": "Sarah Chen",
        "nom": "Sarah Chen",
        "job_title": "VP of Sales",
        "titre": "VP of Sales",
        "email": "sarah.chen@techcorp.com",
        "country": "United States",
        "city": "San Francisco",
        "location": "San Francisco, United States",
        "linkedin": "https://linkedin.com/in/sarahchen",
        "phone": "",
        "is_connected_on_linkedin": False,
    },
    "contexte_web": {
        "profil_brut": "Sarah is a VP of Sales at TechCorp Solutions, a mid-size SaaS company. She recently posted about improving SDR efficiency.",
        "offer_context": "AI-powered outreach automation",
        "icp_description": "SaaS companies with 50-500 employees looking to improve outbound sales",
    },
    "is_connected_on_linkedin": False,
    "use_native_language": False,
    "approval_mode": "per_sequence",
    "sender_company": "OutreachAI Inc",
    "sender_elevator_pitch": "We help SaaS companies automate their outbound sales with AI-powered personalization",
    "offer_name": "Free Outreach Audit",
    "solution_summary": "AI-driven analysis of your current outreach workflow with actionable improvements",
    "cta": "Book a 15-minute strategy call",
    "debug_mode": True,
}

print("=" * 60)
print("LIVE END-TO-END PIPELINE TEST")
print("=" * 60)
print(f"\n1. Sending pipeline request to orchestrator ({ORCHESTRATOR_URL}/api/run)...")
print(f"   Lead: {payload['contact_info']['full_name']} @ {payload['entreprise']}")
print(f"   Debug mode: {payload['debug_mode']}")
print()

start = time.time()

req = urllib.request.Request(
    f"{ORCHESTRATOR_URL}/api/run",
    data=json.dumps(payload).encode("utf-8"),
    headers={"Content-Type": "application/json"},
    method="POST",
)

try:
    with urllib.request.urlopen(req, timeout=300) as resp:
        result = json.loads(resp.read())
    elapsed = time.time() - start

    print(f"2. Pipeline completed in {elapsed:.1f}s")
    print(f"   Status: {result.get('status', 'unknown')}")
    print(f"   Debug mode: {result.get('debug_mode', 'N/A')}")
    print(f"   Errors: {result.get('errors', [])}")
    print()

    # Check sequence result
    seq = result.get("sequence_result", {})
    if seq:
        print("3. Sequence Generator Result:")
        print(f"   Thread ID: {seq.get('thread_id', 'N/A')}")
        print(f"   Status: {seq.get('status', 'N/A')}")
        steps = seq.get("sequence", seq.get("steps", []))
        if isinstance(steps, list):
            print(f"   Steps generated: {len(steps)}")
            for i, step in enumerate(steps[:3], 1):
                channel = step.get("channel", "N/A")
                msg = step.get("message", step.get("generated_message", ""))
                score = step.get("quality_score", step.get("score", "N/A"))
                preview = (msg[:80] + "...") if isinstance(msg, str) and len(msg) > 80 else msg
                print(f"   Step {i}: {channel} | score={score} | {preview}")
        print()
    else:
        print("3. No sequence result returned")
        print()

    # Check observability
    obs = result.get("observability_snapshot", {})
    if obs and "error" not in obs:
        combined = obs.get("combined", {})
        print("4. Observability Snapshot:")
        print(f"   Total tokens: {combined.get('total_tokens', 0)}")
        print(f"   Total LLM calls: {combined.get('total_llm_calls', 0)}")
        print(f"   Tokens in: {combined.get('total_tokens_in', 0)}")
        print(f"   Tokens out: {combined.get('total_tokens_out', 0)}")
    else:
        print(f"4. Observability: {obs}")

    print()
    print("=" * 60)
    if result.get("status") in ("completed", "awaiting_approval"):
        print("END-TO-END TEST: PASSED")
    else:
        print(f"END-TO-END TEST: COMPLETED WITH STATUS '{result.get('status')}'")
    print("=" * 60)

except Exception as e:
    elapsed = time.time() - start
    print(f"\nPIPELINE FAILED after {elapsed:.1f}s")
    print(f"Error: {e}")
    if hasattr(e, 'read'):
        body = e.read().decode('utf-8', errors='replace')
        print(f"Response body: {body[:500]}")

# Also test observability endpoint separately
print("\n5. Testing /api/observability endpoint...")
try:
    obs_resp = urllib.request.urlopen(f"{ORCHESTRATOR_URL}/api/observability")
    obs_data = json.loads(obs_resp.read())
    combined = obs_data.get("combined", {})
    print(f"   Combined tokens: {combined.get('total_tokens', 0)}")
    print(f"   Combined LLM calls: {combined.get('total_llm_calls', 0)}")
    print(f"   Errors: {obs_data.get('errors', [])}")
except Exception as e:
    print(f"   Observability endpoint failed: {e}")

# Test prompt history
print("\n6. Testing /api/observability/prompts endpoint...")
try:
    prompts_resp = urllib.request.urlopen(f"{ORCHESTRATOR_URL}/api/observability/prompts?limit=5")
    prompts = json.loads(prompts_resp.read())
    print(f"   Prompt records returned: {len(prompts)}")
    for p in prompts[:3]:
        print(f"   - [{p.get('module', '?')}] {p.get('agent_step', '?')}: tokens_in={p.get('tokens_in', 0)}, tokens_out={p.get('tokens_out', 0)}")
except Exception as e:
    print(f"   Prompt history failed: {e}")
