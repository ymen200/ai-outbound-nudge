"""
Comprehensive integration tests for the Outreach-Project.

Tests:
1. Health checks for all services
2. Orchestrator capabilities / agent card
3. Sequence generator API (direct)
4. Orchestrator full pipeline
5. Config override propagation
6. Observability endpoints
7. Memory flush
8. Human-in-the-loop approval (sequence generator)
9. InMail routing

Run with:
    cd c:\\Users\\ASUS\\Desktop\\Outreach-Project
    .\\venv\\Scripts\\python.exe scripts\\run_comprehensive_tests.py
"""

import requests
import time
import sys
import json

# Endpoints
ORCH_URL = "http://localhost:8002"
SEQ_URL = "http://localhost:8001"
MSG_URL = "http://localhost:8000"
TIMEOUT = 120


def log(title, msg=""):
    print(f"\n{'='*60}")
    print(f"{title}")
    if msg:
        print(f"  {msg}")
    print(f"{'='*60}")


def test_health():
    log("TEST 1: Service Health")
    results = []
    try:
        r = requests.get(f"{ORCH_URL}/api/health", timeout=10)
        data = r.json()
        print(f"  Orchestrator /api/health: {r.status_code}")
        print(f"    sequence_generator: {data.get('sequence_generator')}")
        print(f"    message_generator: {data.get('message_generator')}")
        results.append(("Orchestrator health", r.status_code == 200))
    except Exception as e:
        print(f"  ERROR: {e}")
        results.append(("Orchestrator health", False))

    try:
        r = requests.get(f"{ORCH_URL}/", timeout=10)
        print(f"  Orchestrator root: {r.status_code}")
        results.append(("Orchestrator root", r.status_code == 200))
    except Exception as e:
        print(f"  ERROR: {e}")
        results.append(("Orchestrator root", False))

    return results


def test_capabilities():
    log("TEST 2: Orchestrator Capabilities / Agent Card")
    try:
        r = requests.get(f"{ORCH_URL}/api/capabilities", timeout=10)
        data = r.json()
        print(f"  Status: {r.status_code}")
        print(f"  supported_channels: {data.get('supported_channels')}")
        print(f"  mcp_tools: {data.get('mcp_tools')}")
        ok = r.status_code == 200 and "linkedin_inmail" in data.get("supported_channels", [])
        print(f"  InMail channel listed: {'YES' if ok else 'NO'}")
        return [("Capabilities / agent card", ok)]
    except Exception as e:
        print(f"  ERROR: {e}")
        return [("Capabilities / agent card", False)]


def test_observability():
    log("TEST 3: Observability Endpoints")
    results = []
    for base, name in [(ORCH_URL, "Orchestrator"), (SEQ_URL, "Sequence Generator"), (MSG_URL, "Message Generator")]:
        try:
            r = requests.get(f"{base}/api/observability", timeout=10)
            print(f"  {name} /api/observability: {r.status_code}")
            if r.status_code == 200:
                data = r.json()
                print(f"    total_calls: {data.get('total_calls')}")
                print(f"    total_tokens: {data.get('total_tokens')}")
                print(f"    success_rate: {data.get('success_rate')}")
            results.append((f"{name} observability", r.status_code == 200))
        except Exception as e:
            print(f"  ERROR {name}: {e}")
            results.append((f"{name} observability", False))
    return results


def test_config_override():
    log("TEST 4: Config Override Propagation")
    results = []
    try:
        # Override sequence generator config
        r = requests.post(
            f"{ORCH_URL}/api/config/override",
            json={"module": "sequence_generator", "overrides": {"GEMINI_TEMPERATURE": "0.3"}},
            timeout=10,
        )
        print(f"  Override sequence_generator GEMINI_TEMPERATURE: {r.status_code}")
        print(f"    Response: {r.json()}")
        results.append(("Config override sequence_generator", r.status_code == 200))

        # Reset
        r = requests.post(
            f"{ORCH_URL}/api/config/reset",
            json={"module": "sequence_generator"},
            timeout=10,
        )
        print(f"  Reset sequence_generator config: {r.status_code}")
        results.append(("Config reset sequence_generator", r.status_code == 200))
    except Exception as e:
        print(f"  ERROR: {e}")
        results.append(("Config override propagation", False))
    return results


def test_feedback_injection():
    log("TEST 5: Feedback Injection")
    try:
        r = requests.post(
            f"{ORCH_URL}/api/feedback",
            json={"module": "sequence_generator", "feedback": "Make the first touch more casual."},
            timeout=10,
        )
        print(f"  Feedback injection: {r.status_code}")
        print(f"    Response: {r.json()}")
        return [("Feedback injection", r.status_code == 200)]
    except Exception as e:
        print(f"  ERROR: {e}")
        return [("Feedback injection", False)]


def make_sequence_payload(lead_id, has_inmail):
    return {
        "lead_id": lead_id,
        "campaign_id": "comprehensive_test",
        "company": "Acme Corp",
        "contact": {
            "full_name": "Jane Doe",
            "job_title": "VP of Engineering",
            "email": "jane@acme.com",
            "country": "United States",
            "city": "New York",
            "location": "New York, United States",
            "linkedin": "https://linkedin.com/in/janedoe",
            "is_connected_on_linkedin": False,
            "has_inmail_credits": has_inmail,
        },
        "web_context": {
            "profil_brut": "Jane is VP of Engineering at Acme Corp, active on LinkedIn, speaks at tech conferences.",
            "offer_context": "We offer AI-powered sales automation.",
            "icp_description": "Engineering leaders at B2B SaaS companies.",
        },
        "sender_info": {
            "company_name": "OutreachAI",
            "elevator_pitch": "AI-driven outbound sequences that convert.",
            "offer_name": "OutreachAI Pro",
            "solution_summary": "Automated multi-channel outreach with AI-generated messages.",
            "cta": "Book a 15-min demo",
        },
        "approval_mode": "per_sequence",
        "preferred_first_channel": "linkedin_inmail",
    }


def find_first_linkedin_step(steps):
    for s in steps:
        action = s.get("action_type", "").upper()
        channel = s.get("channel", "")
        if "LINKEDIN" in action or "linkedin" in channel:
            return s
    return None


def test_sequence_generator_inmail():
    log("TEST 6: Sequence Generator InMail Routing")
    results = []

    # Test 6a: InMail available
    print("  6a. has_inmail_credits=True, is_connected=False")
    try:
        r = requests.post(
            f"{SEQ_URL}/api/generate/sequence",
            json=make_sequence_payload("test-inmail-yes", True),
            timeout=TIMEOUT,
        )
        data = r.json()
        step = find_first_linkedin_step(data.get("steps", []))
        if step and step["action_type"] == "LINKEDIN_INMAIL" and step["channel"] == "linkedin_inmail":
            print(f"    PASS: {step['action_type']} / {step['channel']}")
            results.append(("InMail routing: credits available", True))
        else:
            print(f"    FAIL: {step}")
            results.append(("InMail routing: credits available", False))
    except Exception as e:
        print(f"    ERROR: {e}")
        results.append(("InMail routing: credits available", False))

    # Test 6b: InMail NOT available
    print("  6b. has_inmail_credits=False, is_connected=False")
    try:
        r = requests.post(
            f"{SEQ_URL}/api/generate/sequence",
            json=make_sequence_payload("test-inmail-no", False),
            timeout=TIMEOUT,
        )
        data = r.json()
        step = find_first_linkedin_step(data.get("steps", []))
        if step and step["action_type"] == "LINKEDIN_CONNECT" and step["channel"] == "linkedin_dm":
            print(f"    PASS: {step['action_type']} / {step['channel']}")
            results.append(("InMail routing: fallback to CONNECT", True))
        else:
            print(f"    FAIL: {step}")
            results.append(("InMail routing: fallback to CONNECT", False))
    except Exception as e:
        print(f"    ERROR: {e}")
        results.append(("InMail routing: fallback to CONNECT", False))

    return results


def test_orchestrator_pipeline():
    log("TEST 7: Orchestrator Full Pipeline")
    try:
        payload = {
            "lead_id": "test-orchestrator-001",
            "campaign_id": "comprehensive_test",
            "entreprise": "Acme Corp",
            "contact_info": {
                "full_name": "Jane Doe",
                "job_title": "VP of Engineering",
                "email": "jane@acme.com",
                "country": "United States",
                "city": "New York",
                "location": "New York, United States",
                "linkedin": "https://linkedin.com/in/janedoe",
                "is_connected_on_linkedin": False,
                "has_inmail_credits": True,
            },
            "contexte_web": {
                "profil_brut": "Jane is VP of Engineering at Acme Corp, active on LinkedIn.",
                "offer_context": "AI-powered sales automation.",
                "icp_description": "Engineering leaders.",
            },
            "research_signals": [
                {"type": "recent_post", "content": "Active on LinkedIn", "strength": "medium", "why_relevant": "Engagement"}
            ],
            "is_connected_on_linkedin": False,
            "has_inmail_credits": True,
            "use_native_language": False,
            "message_language": None,
            "approval_mode": "per_sequence",
            "sender_company": "OutreachAI",
            "sender_elevator_pitch": "AI-driven outbound sequences.",
            "offer_name": "OutreachAI Pro",
            "solution_summary": "Automated multi-channel outreach.",
            "cta": "Book a 15-min demo",
            "max_touches": 3,
            "max_days": 10,
            "preferred_first_channel": "linkedin_inmail",
            "debug_mode": True,
        }

        start = time.time()
        r = requests.post(f"{ORCH_URL}/api/run", json=payload, timeout=TIMEOUT)
        elapsed = time.time() - start
        data = r.json()

        print(f"  Status code: {r.status_code}")
        print(f"  Elapsed: {elapsed:.2f}s")
        print(f"  Response status: {data.get('status')}")
        print(f"  Thread ID: {data.get('thread_id')}")
        print(f"  Errors: {data.get('errors', [])}")

        seq = data.get("sequence_result", {})
        print(f"  Total steps: {seq.get('total_steps')}")
        for s in seq.get("steps", []):
            print(f"    Step {s['step_number']}: {s['action_type']} / {s['channel']}")

        step = find_first_linkedin_step(seq.get("steps", []))
        ok = (
            r.status_code == 200
            and data.get("status") in ("awaiting_approval", "completed")
            and step
            and step["action_type"] == "LINKEDIN_INMAIL"
            and step["channel"] == "linkedin_inmail"
        )
        if ok:
            print("  PASS: Orchestrator propagated has_inmail_credits and generated InMail step")
        else:
            print(f"  FAIL: {step}")

        return [("Orchestrator full pipeline", ok), ("Orchestrator InMail propagation", ok)]
    except Exception as e:
        print(f"  ERROR: {e}")
        return [("Orchestrator full pipeline", False)]


def test_human_in_the_loop():
    log("TEST 8: Human-in-the-Loop Approval (Sequence Generator)")
    try:
        payload = make_sequence_payload("test-hilt-001", False)
        r = requests.post(f"{SEQ_URL}/api/generate/sequence", json=payload, timeout=TIMEOUT)
        data = r.json()

        if data.get("status") != "awaiting_approval":
            print(f"  FAIL: Expected awaiting_approval, got {data.get('status')}")
            return [("HILT approval flow", False)]

        thread_id = data.get("thread_id")
        print(f"  Generated sequence, thread_id: {thread_id}")

        # Approve
        r = requests.post(
            f"{SEQ_URL}/api/approve/{thread_id}",
            json={"approved": True},
            timeout=TIMEOUT,
        )
        approve_data = r.json()
        print(f"  Approve response status: {r.status_code}")
        print(f"    status: {approve_data.get('status')}")
        print(f"    temporal_dispatch: {approve_data.get('temporal_dispatch', {}).get('status') if isinstance(approve_data.get('temporal_dispatch'), dict) else approve_data.get('temporal_dispatch')}")

        ok = r.status_code == 200 and approve_data.get("status") in ("approved", "dispatched", "completed")
        return [("HILT approval flow", ok)]
    except Exception as e:
        print(f"  ERROR: {e}")
        return [("HILT approval flow", False)]


def main():
    print("OUTREACH-PROJECT COMPREHENSIVE TEST SUITE")
    print(f"Started at: {time.strftime('%Y-%m-%d %H:%M:%S')}")

    all_results = []
    all_results.extend(test_health())
    all_results.extend(test_capabilities())
    all_results.extend(test_observability())
    all_results.extend(test_config_override())
    all_results.extend(test_feedback_injection())
    all_results.extend(test_sequence_generator_inmail())
    all_results.extend(test_orchestrator_pipeline())
    all_results.extend(test_human_in_the_loop())

    log("FINAL SUMMARY")
    passed = 0
    failed = 0
    for name, ok in all_results:
        tag = "PASS" if ok else "FAIL"
        print(f"  [{tag}] {name}")
        if ok:
            passed += 1
        else:
            failed += 1

    print(f"\nTotal: {passed} passed, {failed} failed out of {len(all_results)}")
    sys.exit(0 if failed == 0 else 1)


if __name__ == "__main__":
    main()
