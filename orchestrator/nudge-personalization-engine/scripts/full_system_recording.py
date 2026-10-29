"""
Full System Recording Script
=============================
Exercises the complete Outreach pipeline end-to-end:
  Orchestrator (8002) → Sequence Generator (8001) → Message Generator (8000)

Logs every HTTP call (timestamp, description, method, URL, request body,
response status + body) to a timestamped file in recordings/.
Prints live progress to the terminal.

Usage:
    python scripts/full_system_recording.py

Assumes all services are already running.
"""

import json
import time
import sys
import os
import io
from datetime import datetime, timezone
from pathlib import Path

# Force UTF-8 output on Windows terminals
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

try:
    import httpx
except ImportError:
    print("ERROR: httpx not installed. Run: pip install httpx")
    sys.exit(1)

# ── Configuration ──────────────────────────────────────────────────
MSG_GEN = "http://localhost:8000"
SEQ_GEN = "http://localhost:8001"
ORCHESTRATOR = "http://localhost:8002"
TIMEOUT = httpx.Timeout(120.0, connect=10.0)

RECORDINGS_DIR = Path(__file__).resolve().parent.parent / "recordings"
RECORDINGS_DIR.mkdir(exist_ok=True)

# ── Logging ────────────────────────────────────────────────────────
log_lines: list[str] = []
call_count = 0
error_count = 0


def log(msg: str):
    """Print to terminal AND append to log buffer."""
    ts = datetime.now().strftime("%H:%M:%S.%f")[:-3]
    line = f"[{ts}] {msg}"
    print(line, flush=True)
    log_lines.append(line)


def record_call(description: str, method: str, url: str,
                request_body: dict | None, response_status: int,
                response_body: str, elapsed_ms: float):
    """Log a full HTTP call to the recording file."""
    global call_count
    call_count += 1
    separator = "─" * 72
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
    entry = f"""
{separator}
CALL #{call_count}  |  {ts}
Description : {description}
Request     : {method} {url}
Body Sent   : {json.dumps(request_body, indent=2, default=str) if request_body else '(none)'}
Response    : HTTP {response_status}  ({elapsed_ms:.0f} ms)
Body Recv'd : {response_body[:3000]}{'...(truncated)' if len(response_body) > 3000 else ''}
{separator}"""
    log_lines.append(entry)
    print(f"  → HTTP {response_status} ({elapsed_ms:.0f} ms)")


def do_call(description: str, method: str, url: str,
            body: dict | None = None) -> tuple[int, dict | str]:
    """Execute an HTTP call, log it, return (status, parsed_body)."""
    global error_count
    start = time.time()
    try:
        with httpx.Client(timeout=TIMEOUT) as client:
            if method == "GET":
                resp = client.get(url)
            elif method == "POST":
                resp = client.post(url, json=body)
            else:
                raise ValueError(f"Unsupported method: {method}")

        elapsed = (time.time() - start) * 1000
        status = resp.status_code
        try:
            resp_body = resp.json()
            resp_str = json.dumps(resp_body, indent=2, default=str)
        except Exception:
            resp_body = resp.text
            resp_str = resp.text

        record_call(description, method, url, body, status, resp_str, elapsed)
        if status >= 400:
            error_count += 1
            log(f"  ⚠ ERROR: HTTP {status}")
        return status, resp_body

    except Exception as e:
        elapsed = (time.time() - start) * 1000
        record_call(description, method, url, body, 0, f"EXCEPTION: {e}", elapsed)
        error_count += 1
        return 0, {"error": str(e)}


# ── Test Data ──────────────────────────────────────────────────────
PIPELINE_PAYLOAD = {
    "entreprise": "DataFlow AI",
    "lead_id": "recording-lead-001",
    "campaign_id": "recording-campaign-001",
    "contact_info": {
        "full_name": "Marie Laurent",
        "role": "VP Engineering",
        "company": "DataFlow AI",
        "city": "Paris",
        "location": "Paris, France",
        "email": "marie.laurent@dataflow-ai.example.com",
        "linkedin": "https://linkedin.com/in/marie-laurent-example",
        "is_connected_on_linkedin": False,
        "has_inmail_credits": False,
    },
    "contexte_web": {
        "profil_brut": "VP Engineering at DataFlow AI, a Series B startup building "
                       "real-time data pipeline tools. 200 employees. Recently raised $30M.",
        "offer_context": "We provide automated data quality monitoring that catches "
                        "pipeline failures before they impact customers.",
        "icp_description": "Series A-C tech companies with 50-500 employees, "
                          "running production data pipelines.",
    },
    "sender_company": "PipelineGuard",
    "sender_elevator_pitch": "We monitor your data pipelines 24/7 and catch failures "
                            "before your customers notice.",
    "offer_name": "Free Pipeline Audit",
    "solution_summary": "Comprehensive audit of your data pipeline health with "
                       "actionable recommendations.",
    "cta": "Book a 15-minute audit call",
    "approval_mode": "per_sequence",
    "max_touches": 3,
    "debug_mode": True,
}

REJECT_FEEDBACK = (
    "The sequence is too email-heavy. Please include at least one LinkedIn touch "
    "before the email follow-up. Also make the tone more conversational and less salesy."
)

MSG_GEN_FEEDBACK = (
    "When generating messages for this prospect, emphasize the ROI angle — "
    "mention specific metrics like '99.9% pipeline uptime' and '40% faster incident response'."
)

# ── Message Generator direct payload (for Step 5 feedback comparison) ──
# Both cases use identical payloads except for user_feedback.
# The payload is designed to be simple enough to pass critic without feedback.
MSG_GEN_DIRECT_PAYLOAD = {
    "target_prospect": "Marie Laurent",
    "target_company": "DataFlow AI",
    "prospect_role": "VP Engineering",
    "channel": "email",
    "intent": "direct_outreach",
    "stage": "first_touch",
    "personality": {
        "analysis": "Data-driven, strategic thinker who values concrete metrics",
        "custom_template_description": "Professional and concise. Lead with a specific metric or pain point. Keep it under 500 characters.",
        "touchdowns_per_message": 1,
        "urgency_level": 3,
        "humor_sarcasm": 1,
        "self_deprecation": 1,
    },
    "company_details": {
        "company_name": "PipelineGuard",
        "elevator_pitch": "We monitor your data pipelines 24/7 and catch failures before your customers notice.",
        "industry": "DevOps / Data Infrastructure",
        "website": "https://pipelineguard.example.com",
        "value_props": [
            "99.9% pipeline uptime guarantee",
            "40% faster incident response",
        ],
        "social_proof": ["Used by 50+ Series B+ data teams"],
    },
    "selected_offer": {
        "offer_name": "Free Pipeline Audit",
        "solution_summary": "Comprehensive audit of your data pipeline health with actionable recommendations.",
        "cta": "Book a 15-minute audit call",
        "pain_points": ["Silent pipeline failures", "Slow incident response"],
        "proof_points": ["99.9% uptime", "40% faster response"],
    },
}

# Feedback that specifically asks to include metrics — this is the ONLY difference
FEEDBACK_WITH_METRICS = (
    "Make sure to mention specific metrics: 99.9% pipeline uptime and 40% faster incident response."
)


def _extract_thread_ids(paused_response) -> list[str]:
    """Extract thread_id list from paused-threads response."""
    threads = []
    if isinstance(paused_response, list):
        threads = paused_response
    elif isinstance(paused_response, dict):
        threads = paused_response.get("threads", paused_response.get("paused_threads", []))
    return [t.get("thread_id") or t.get("thread") for t in threads if t]


def _flush_log(log_file):
    """Write current log buffer to file (incremental save)."""
    with open(log_file, "w", encoding="utf-8") as f:
        f.write("\n".join(log_lines))


# ── Main Flow ──────────────────────────────────────────────────────
def main():
    global error_count
    start_time = time.time()
    recording_ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_file = RECORDINGS_DIR / f"recording_{recording_ts}.log"

    log("=" * 72)
    log("FULL SYSTEM RECORDING — START")
    log("=" * 72)
    log(f"Recording file: {log_file}")
    log(f"Services: Orchestrator={ORCHESTRATOR}, SeqGen={SEQ_GEN}, MsgGen={MSG_GEN}")
    log("")

    # ── Phase 1: Health Checks ─────────────────────────────────────
    log("═══ PHASE 1: Health & Status Checks ═══")
    log("")

    do_call("Message Generator — root health", "GET", f"{MSG_GEN}/")
    do_call("Message Generator — memory status", "GET", f"{MSG_GEN}/api/memory/status")
    do_call("Message Generator — observability", "GET", f"{MSG_GEN}/api/observability")

    do_call("Sequence Generator — health", "GET", f"{SEQ_GEN}/health")
    do_call("Sequence Generator — memory status", "GET", f"{SEQ_GEN}/api/memory/status")
    do_call("Sequence Generator — observability", "GET", f"{SEQ_GEN}/api/observability")
    do_call("Sequence Generator — paused threads", "GET", f"{SEQ_GEN}/api/paused-threads")

    do_call("Orchestrator — root health", "GET", f"{ORCHESTRATOR}/")
    do_call("Orchestrator — health (deep)", "GET", f"{ORCHESTRATOR}/api/health")
    do_call("Orchestrator — capabilities", "GET", f"{ORCHESTRATOR}/api/capabilities")
    do_call("Orchestrator — observability", "GET", f"{ORCHESTRATOR}/api/observability")

    log("")
    log(f"Phase 1 complete. Errors so far: {error_count}")
    log("")
    _flush_log(log_file)

    # ── Phase 2: Submit Pipeline via Orchestrator ──────────────────
    log("═══ PHASE 2: Submit Pipeline (Orchestrator → SeqGen → MsgGen) ═══")
    log("")

    status, result = do_call(
        "Submit full pipeline via Orchestrator",
        "POST", f"{ORCHESTRATOR}/api/run", PIPELINE_PAYLOAD
    )

    thread_id = None
    lead_id = PIPELINE_PAYLOAD["lead_id"]

    if isinstance(result, dict):
        thread_id = result.get("thread_id")
        if not thread_id and "sequence_result" in result:
            thread_id = result["sequence_result"].get("thread_id")
        if not thread_id:
            for key in ["thread_id", "id"]:
                if key in result:
                    thread_id = result[key]
                    break

    if not thread_id:
        log(f"  ⚠ No thread_id in response. Attempting to find via paused-threads...")
        status2, paused = do_call(
            "Check paused threads to find thread_id",
            "GET", f"{SEQ_GEN}/api/paused-threads"
        )
        tids = _extract_thread_ids(paused)
        if tids:
            thread_id = tids[0]

    if thread_id:
        log(f"  ✓ Thread ID: {thread_id}")
    else:
        log(f"  ⚠ Could not determine thread_id. Continuing with best effort...")
        thread_id = "unknown"

    log("")
    _flush_log(log_file)

    # ── Phase 3: Check Paused Threads ──────────────────────────────
    log("═══ PHASE 3: Verify Paused Thread ═══")
    log("")

    do_call(
        "Check paused threads (should show our thread)",
        "GET", f"{SEQ_GEN}/api/paused-threads"
    )
    log("")

    # ── Phase 4: Inject Feedback to Sequence Generator ─────────────
    log("═══ PHASE 4: Inject Feedback to Sequence Generator ═══")
    log("")

    do_call(
        "Inject feedback to Sequence Generator (lead-scoped)",
        "POST", f"{SEQ_GEN}/api/feedback",
        {"feedback": REJECT_FEEDBACK, "lead_id": lead_id}
    )
    log("")

    # ── Phase 5: Inject Feedback to Message Generator (standalone) ─
    log("═══ PHASE 5: Inject Feedback to Message Generator (standalone) ═══")
    log("")

    do_call(
        "Inject feedback directly to Message Generator /api/feedback",
        "POST", f"{MSG_GEN}/api/feedback",
        {"feedback": MSG_GEN_FEEDBACK}
    )
    log("")
    _flush_log(log_file)

    # ── Phase 6: Snapshot thread content BEFORE reject ─────────────
    log("═══ PHASE 6: Snapshot Thread Content Before Reject ═══")
    log("")

    status, paused_before = do_call(
        "Snapshot paused threads BEFORE reject",
        "GET", f"{SEQ_GEN}/api/paused-threads"
    )
    threads_before = set(_extract_thread_ids(paused_before))
    log(f"  Threads before reject: {threads_before}")

    # Also snapshot the reject response to detect content change
    log("")

    # ── Phase 7: Reject Sequence with Feedback → Triggers Regen ────
    log("═══ PHASE 7: Reject Sequence (triggers regeneration) ═══")
    log("")

    reject_body = {"approved": False, "user_feedback": REJECT_FEEDBACK}
    status, reject_result = do_call(
        f"Reject sequence {thread_id} with feedback",
        "POST", f"{SEQ_GEN}/api/approve/{thread_id}",
        reject_body
    )

    # Capture the regenerated sequence from the reject response
    regen_status = ""
    regen_steps = []
    if isinstance(reject_result, dict):
        regen_status = reject_result.get("status", "")
        final_state = reject_result.get("final_state")
        if isinstance(final_state, dict):
            steps = final_state.get("steps", [])
            regen_steps = [f"{s.get('action_type', '?')}/{s.get('channel', '?')}" for s in steps]
        elif isinstance(final_state, list):
            regen_steps = [f"{s.get('action_type', '?')}/{s.get('channel', '?')}" for s in final_state]
        log(f"  Reject response status: {regen_status}")
        log(f"  Regenerated sequence steps: {regen_steps}")
        if reject_result.get("user_feedback_applied"):
            log(f"  Feedback applied: {reject_result['user_feedback_applied'][:200]}")
    log("")

    # ── Phase 8: Confirm Regenerated Thread ────────────────────────
    log("═══ PHASE 8: Confirm Regenerated Thread ═══")
    log("")

    # LangGraph reuses the same thread_id for regeneration (in-place update).
    # The approve_and_dispatch endpoint runs regeneration synchronously,
    # so by the time the reject response returns, the thread already has
    # the new sequence. We confirm by checking the thread is still paused
    # and the reject response showed a regenerated status.
    regen_thread_id = thread_id  # same ID, content replaced in-place

    if regen_status == "regenerated":
        log(f"  ✓ Regeneration confirmed via reject response (status='regenerated')")
        log(f"    Thread {regen_thread_id} now holds the regenerated sequence")
        log(f"    New steps: {regen_steps}")
    else:
        # Fallback: verify thread is still in paused-threads
        status, paused_after = do_call(
            "Verify thread still paused after regeneration",
            "GET", f"{SEQ_GEN}/api/paused-threads"
        )
        if regen_thread_id in _extract_thread_ids(paused_after):
            log(f"  ✓ Thread {regen_thread_id} still paused — regeneration likely complete")
        else:
            log(f"  ⚠ Thread {regen_thread_id} not found in paused-threads")
    log("")
    _flush_log(log_file)

    # ── Phase 9: Approve Regenerated Sequence ──────────────────────
    log("═══ PHASE 9: Approve Regenerated Sequence ═══")
    log("")

    approve_body = {"approved": True, "user_feedback": None}
    status, approve_result = do_call(
        f"Approve regenerated sequence {regen_thread_id}",
        "POST", f"{SEQ_GEN}/api/approve/{regen_thread_id}",
        approve_body
    )

    # Extract temporal_workflow_id from approve response
    temporal_workflow_id = None
    if isinstance(approve_result, dict):
        temporal_workflow_id = approve_result.get("temporal_workflow_id")
        if temporal_workflow_id:
            log(f"  ✓ Temporal workflow ID: {temporal_workflow_id}")
        else:
            log(f"  ⚠ No temporal_workflow_id in approve response")
    log("")

    # ── Phase 10: Confirm Dispatch ─────────────────────────────────
    log("═══ PHASE 10: Confirm Dispatch (thread left paused-threads) ═══")
    log("")

    dispatch_confirmed = False
    for attempt in range(1, 11):
        log(f"  Dispatch check #{attempt}: verifying thread left paused-threads...")
        status, paused = do_call(
            f"Verify dispatch (attempt {attempt})",
            "GET", f"{SEQ_GEN}/api/paused-threads"
        )

        active_ids = _extract_thread_ids(paused)
        if regen_thread_id not in active_ids:
            dispatch_confirmed = True
            log(f"  ✓ Thread {regen_thread_id} has been dispatched (no longer paused)")
            break

        if attempt < 10:
            log(f"  Thread still paused. Waiting 2s...")
            time.sleep(2)

    if not dispatch_confirmed:
        log(f"  ⚠ Thread still in paused-threads after 10 attempts.")
        log(f"    NOTE: dispatch_to_temporal may have failed (check logs).")

    log("")
    _flush_log(log_file)

    # ── Phase 11: Wait for JIT Message Generation ──────────────────
    log("═══ PHASE 11: Wait for JIT Message Generation ═══")
    log("")

    msg_gen_calls_before = 0
    status, obs = do_call(
        "Message Generator — observability (pre-wait snapshot)",
        "GET", f"{MSG_GEN}/api/observability"
    )
    if isinstance(obs, dict):
        msg_gen_calls_before = obs.get("total_llm_calls", 0)
        log(f"  Message Generator total_llm_calls before wait: {msg_gen_calls_before}")

    # If we have a real Temporal workflow, send approve_sequence signal
    if temporal_workflow_id and not temporal_workflow_id.startswith("SIMULATED"):
        log(f"  Sending approve_sequence signal to Temporal workflow {temporal_workflow_id}...")
        try:
            import asyncio as _asyncio
            from temporalio.client import Client as _TemporalClient

            async def _send_approve_signal():
                tc = await _TemporalClient.connect("localhost:7233")
                wh = tc.get_workflow_handle(temporal_workflow_id)
                await wh.signal("approve_sequence")
                return True

            # Run in thread if needed
            try:
                _asyncio.get_running_loop()
                import threading as _th
                sig_result = [None]
                def _sig_target():
                    sig_result[0] = _asyncio.run(_send_approve_signal())
                _t = _th.Thread(target=_sig_target)
                _t.start()
                _t.join(timeout=10)
            except RuntimeError:
                _asyncio.run(_send_approve_signal())
            log(f"  ✓ approve_sequence signal sent successfully")
        except Exception as e:
            log(f"  ⚠ Failed to send approve signal: {e}")
        log("")

    # Poll Message Generator observability until total_llm_calls increases
    jit_confirmed = False
    for attempt in range(1, 21):  # up to 40 seconds
        log(f"  JIT poll #{attempt}: checking Message Generator observability...")
        status, obs = do_call(
            f"Message Generator — observability (JIT poll {attempt})",
            "GET", f"{MSG_GEN}/api/observability"
        )
        if isinstance(obs, dict):
            current_calls = obs.get("total_llm_calls", 0)
            log(f"    total_llm_calls = {current_calls}")
            if current_calls > msg_gen_calls_before:
                jit_confirmed = True
                log(f"  ✓ JIT message generation confirmed! "
                    f"total_llm_calls went from {msg_gen_calls_before} → {current_calls}")
                break
        if attempt < 20:
            time.sleep(2)

    if not jit_confirmed:
        log(f"  ⚠ JIT message generation NOT detected after 60s.")
        log(f"    NOTE: Temporal workflow may not be running (need temporal server + worker).")
        log(f"    The dispatch_to_temporal starts a real workflow, but activities won't")
        log(f"    execute unless a Temporal worker is polling the task queue.")

    log("")

    # ── Phase 12: Feedback Comparison (with vs without) ────────────
    log("═══ PHASE 12: Message Generation — With vs Without Feedback ═══")
    log("")
    log("  Both cases use IDENTICAL payloads. The ONLY difference is user_feedback.")
    log(f"  Feedback injected: '{FEEDBACK_WITH_METRICS}'")
    log("")

    # (a) Generate WITHOUT feedback
    log("  (a) Generating message WITHOUT feedback...")
    status, msg_no_fb = do_call(
        "Message Generator — generate WITHOUT feedback",
        "POST", f"{MSG_GEN}/api/generate/simple",
        MSG_GEN_DIRECT_PAYLOAD
    )
    msg_no_fb_text = ""
    if isinstance(msg_no_fb, dict):
        msg_no_fb_text = msg_no_fb.get("message", "") or msg_no_fb.get("error", str(msg_no_fb))
    log(f"  Message WITHOUT feedback (first 300 chars): {str(msg_no_fb_text)[:300]}")
    log("")

    # (b) Generate WITH feedback (same payload + user_feedback field)
    log("  (b) Generating message WITH feedback (same payload, user_feedback added)...")
    payload_with_fb = {**MSG_GEN_DIRECT_PAYLOAD, "user_feedback": FEEDBACK_WITH_METRICS}
    status, msg_with_fb = do_call(
        "Message Generator — generate WITH feedback",
        "POST", f"{MSG_GEN}/api/generate/simple",
        payload_with_fb
    )
    msg_with_fb_text = ""
    if isinstance(msg_with_fb, dict):
        msg_with_fb_text = msg_with_fb.get("message", "") or msg_with_fb.get("error", str(msg_with_fb))
    log(f"  Message WITH feedback (first 300 chars): {str(msg_with_fb_text)[:300]}")
    log("")

    # (c) Side-by-side comparison
    log("  ─── SIDE-BY-SIDE COMPARISON ───")
    log(f"  WITHOUT feedback: {str(msg_no_fb_text)[:500]}")
    log(f"  ───")
    log(f"  WITH feedback:    {str(msg_with_fb_text)[:500]}")
    log(f"  ──────────────────────────────")

    # Check for the specific metrics from the feedback
    has_metrics_without = any(m in str(msg_no_fb_text) for m in ["99.9%", "40% faster"])
    has_metrics_with = any(m in str(msg_with_fb_text) for m in ["99.9%", "40% faster"])
    log(f"  Contains '99.9%' or '40% faster' WITHOUT feedback: {has_metrics_without}")
    log(f"  Contains '99.9%' or '40% faster' WITH feedback:    {has_metrics_with}")
    log("")

    # ── Phase 13: Final Observability Snapshot ─────────────────────
    log("═══ PHASE 13: Final Observability Snapshot ═══")
    log("")

    do_call("Orchestrator — final observability", "GET", f"{ORCHESTRATOR}/api/observability")
    do_call("Sequence Generator — final observability", "GET", f"{SEQ_GEN}/api/observability")
    do_call("Message Generator — final observability", "GET", f"{MSG_GEN}/api/observability")

    # ── Summary ────────────────────────────────────────────────────
    elapsed = time.time() - start_time
    log("")
    log("=" * 72)
    log("RECORDING SUMMARY")
    log("=" * 72)
    log(f"  Total HTTP calls     : {call_count}")
    log(f"  Errors               : {error_count}")
    log(f"  Elapsed time         : {elapsed:.1f}s")
    log(f"  Thread ID (initial)  : {thread_id}")
    log(f"  Thread ID (regen)    : {regen_thread_id}")
    log(f"  Temporal workflow ID : {temporal_workflow_id or 'N/A'}")
    log(f"  Dispatch status      : {'CONFIRMED' if dispatch_confirmed else 'NOT CONFIRMED'}")
    log(f"  JIT msg generation   : {'CONFIRMED' if jit_confirmed else 'NOT DETECTED (need Temporal worker)'}")
    log(f"  Recording file       : {log_file}")
    log("=" * 72)
    log("RECORDING COMPLETE")
    log("=" * 72)

    # ── Write log file ─────────────────────────────────────────────
    with open(log_file, "w", encoding="utf-8") as f:
        f.write("\n".join(log_lines))

    print(f"\nRecording saved to: {log_file}")


if __name__ == "__main__":
    main()
