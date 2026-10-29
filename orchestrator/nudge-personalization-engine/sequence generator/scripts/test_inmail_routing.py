"""
Test: LINKEDIN_INMAIL routing behavior.

Test 1: has_inmail_credits=True + is_connected_on_linkedin=False
  -> Expected: First LinkedIn step uses LINKEDIN_INMAIL on channel linkedin_inmail

Test 2: has_inmail_credits=False + is_connected_on_linkedin=False
  -> Expected: First LinkedIn step uses LINKEDIN_CONNECT on channel linkedin_dm
"""

import requests
import json
import sys

API_URL = "http://localhost:8001/api/generate/sequence"
TIMEOUT = 120

BASE_PAYLOAD = {
    "lead_id": "test_inmail",
    "campaign_id": "test_campaign",
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
        "has_inmail_credits": True
    },
    "web_context": {
        "profil_brut": "Jane is a VP of Engineering at Acme Corp, active on LinkedIn, speaks at tech conferences.",
        "offer_context": "We offer AI-powered sales automation.",
        "icp_description": "Engineering leaders at B2B SaaS companies."
    },
    "sender_info": {
        "company_name": "OutreachAI",
        "elevator_pitch": "AI-driven outbound sequences that actually convert.",
        "offer_name": "OutreachAI Pro",
        "solution_summary": "Automated multi-channel outreach with AI-generated messages.",
        "cta": "Book a 15-min demo"
    },
    "approval_mode": "per_sequence"
}


def find_first_linkedin_step(steps):
    for s in steps:
        action = s.get("action_type", "").upper()
        channel = s.get("channel", "")
        if "LINKEDIN" in action or "linkedin" in channel:
            return s
    return None


def run_test(name, has_inmail, is_connected, expect_action, expect_channel):
    print(f"\n{'='*60}")
    print(f"TEST: {name}")
    print(f"  has_inmail_credits={has_inmail}, is_connected={is_connected}")
    print(f"  Expected: {expect_action} on {expect_channel}")
    print(f"{'='*60}")

    payload = json.loads(json.dumps(BASE_PAYLOAD))
    payload["lead_id"] = f"test_{name.replace(' ', '_').lower()}"
    payload["contact"]["has_inmail_credits"] = has_inmail
    payload["contact"]["is_connected_on_linkedin"] = is_connected

    try:
        resp = requests.post(API_URL, json=payload, timeout=TIMEOUT)
        resp.raise_for_status()
    except Exception as e:
        print(f"  ERROR: Request failed: {e}")
        return False

    data = resp.json()
    status = data.get("status", "unknown")
    steps = data.get("steps", [])
    errors = data.get("errors", [])

    print(f"  Response status: {status}")
    print(f"  Total steps: {len(steps)}")
    if errors:
        print(f"  Errors: {errors}")

    for s in steps:
        print(f"    Step {s['step_number']}: action_type={s['action_type']}, channel={s['channel']}")

    linkedin_step = find_first_linkedin_step(steps)
    if linkedin_step is None:
        print(f"  FAIL: No LinkedIn step found in the sequence")
        return False

    actual_action = linkedin_step["action_type"]
    actual_channel = linkedin_step["channel"]

    if actual_action == expect_action and actual_channel == expect_channel:
        print(f"  PASS: First LinkedIn step = {actual_action} on {actual_channel}")
        return True
    else:
        print(f"  FAIL: Expected {expect_action}/{expect_channel}, got {actual_action}/{actual_channel}")
        return False


if __name__ == "__main__":
    results = []

    # Test 1: InMail credits available, not connected -> should use LINKEDIN_INMAIL
    r1 = run_test(
        "InMail credits available",
        has_inmail=True,
        is_connected=False,
        expect_action="LINKEDIN_INMAIL",
        expect_channel="linkedin_inmail"
    )
    results.append(("InMail credits available", r1))

    # Test 2: No InMail credits, not connected -> should fall back to LINKEDIN_CONNECT
    r2 = run_test(
        "No InMail credits (fallback)",
        has_inmail=False,
        is_connected=False,
        expect_action="LINKEDIN_CONNECT",
        expect_channel="linkedin_dm"
    )
    results.append(("No InMail credits (fallback)", r2))

    print(f"\n{'='*60}")
    print("SUMMARY")
    print(f"{'='*60}")
    all_pass = True
    for name, passed in results:
        tag = "PASS" if passed else "FAIL"
        print(f"  [{tag}] {name}")
        if not passed:
            all_pass = False

    print()
    if all_pass:
        print("All tests passed!")
    else:
        print("Some tests failed — see above.")

    sys.exit(0 if all_pass else 1)
