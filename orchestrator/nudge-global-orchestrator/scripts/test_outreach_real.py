"""
Real end-to-end smoke test for the global orchestrator -> Outreach Orchestrator handoff
using the actual stdio MCP server and real downstream services.

Prerequisites:
  - GOOGLE_API_KEY is set in the Outreach-Project sub-module .env files.
  - Temporal CLI is installed and on PATH.
  - Outreach-Project and nudge-global-orchestrator venvs are set up.

Run from the nudge-global-orchestrator directory:
    venv/Scripts/python scripts/test_outreach_real.py
"""

from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Optional
import io

import httpx

REPO_ROOT = Path(__file__).resolve().parent.parent.parent.parent
OUTREACH_ROOT = REPO_ROOT / "Outreach-Project"
OUTREACH_ORCH = OUTREACH_ROOT / "outreach orchestrator"
OUTREACH_MCP_PATH = OUTREACH_ORCH / "run_mcp.py"
OUTREACH_PYTHON = OUTREACH_ORCH / "venv" / "Scripts" / "python.exe"

GLOBAL_ROOT = Path(__file__).resolve().parent.parent
GLOBAL_VENV = GLOBAL_ROOT / "venv" / "Scripts" / "python.exe"

DB_PATH = Path(tempfile.gettempdir()) / "orchestrator_real_test.db"
OUTREACH_LOG = Path(tempfile.gettempdir()) / "outreach_real_test_outreach.log"
GLOBAL_LOG = Path(tempfile.gettempdir()) / "outreach_real_test_global.log"

# Ports used by Outreach Project services and the global orchestrator
SERVICE_PORTS = [8000, 8001, 8002, 7233, 8100]


def _kill_process_by_pid(pid: int) -> None:
    try:
        if os.name == "nt":
            subprocess.run(["taskkill", "/F", "/PID", str(pid)], check=False)
        else:
            subprocess.run(["kill", "-9", str(pid)], check=False)
    except Exception:
        pass


def _kill_listeners_on_port(port: int) -> None:
    """Kill any process currently listening on the given port."""
    try:
        if os.name == "nt":
            # Example line:  TCP    0.0.0.0:8000           0.0.0.0:0              LISTENING       12345
            # Match ":PORT " with a trailing space so e.g. :8000 does not also
            # catch :80000 / :80001.
            result = subprocess.run(
                f'netstat -ano | findstr ":{port} "',
                shell=True,
                capture_output=True,
                text=True,
                check=False,
            )
            for line in result.stdout.splitlines():
                parts = line.strip().split()
                if "LISTENING" in parts:
                    try:
                        pid = int(parts[-1])
                        _kill_process_by_pid(pid)
                    except (ValueError, IndexError):
                        pass
        else:
            result = subprocess.run(
                f"lsof -ti :{port}",
                shell=True,
                capture_output=True,
                text=True,
                check=False,
            )
            for pid_str in result.stdout.splitlines():
                try:
                    _kill_process_by_pid(int(pid_str.strip()))
                except ValueError:
                    pass
    except Exception:
        pass


def _kill_zombie_services() -> None:
    print("Cleaning up any existing processes on test ports...")
    for port in SERVICE_PORTS:
        _kill_listeners_on_port(port)
    time.sleep(1.0)


def _kill_tree(pid: int) -> None:
    """Kill a process and its children."""
    try:
        if os.name == "nt":
            subprocess.run(["taskkill", "/T", "/F", "/PID", str(pid)], check=False)
        else:
            subprocess.run(["kill", "-9", str(pid)], check=False)
    except Exception:
        pass


def _wait_for_socket(port: int, timeout: float = 60.0) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with socket.create_connection(("localhost", port), timeout=1.0):
                return
        except Exception:
            pass
        time.sleep(0.5)
    raise RuntimeError(f"Port {port} did not become ready within {timeout}s")


def _wait_for_http(port: int, path: str, timeout: float = 60.0) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            r = httpx.get(f"http://localhost:{port}{path}", timeout=5.0)
            if r.status_code == 200:
                return
        except Exception:
            pass
        time.sleep(0.5)
    raise RuntimeError(f"HTTP service on port {port} did not become ready within {timeout}s")


def _pprint(title: str, data) -> None:
    print(f"\n{'='*60}")
    print(title)
    print("=" * 60)
    print(json.dumps(data, indent=2, default=str))


def _query_temporal_workflow(workflow_id: str, label: str, max_polls: int = 15) -> dict:
    """Query Temporal workflow state via the Sequence Generator API.

    Polls until the workflow produces a result or max_polls is reached.
    Returns the final state dict or an error dict.

    IMPORTANT — messages may appear null even when the pipeline is healthy:
    * generate_message_activity has a 90 s start_to_close_timeout (see
      sequence_workflow.py). Gemini takes 10‑30 s per message.
    * This poller returns as soon as status == "in_progress", which happens
      while generate_message_activity is still running inside Temporal.
    * Null message bodies at query time are NOT a bug — they mean Gemini
      hasn't returned yet. To see generated messages, either increase
      max_polls or query again after a few seconds.
    """
    url = f"http://localhost:8001/api/workflow/{workflow_id}/state"
    for attempt in range(max_polls):
        try:
            r = httpx.get(url, timeout=10.0)
            r.raise_for_status()
            state = r.json()
            wf_state = state.get("state", {})
            status = wf_state.get("status", "unknown")
            if status in ("completed", "failed", "stopped", "in_progress"):
                _pprint(f"Temporal Workflow State ({label}) [attempt {attempt + 1}]", state)
                return state
            if attempt == 0 or attempt % 3 == 0:
                print(f"  Temporal poll {attempt + 1}/{max_polls}: status={status}")
        except Exception as exc:
            if attempt == 0 or attempt % 3 == 0:
                print(f"  Temporal poll {attempt + 1}/{max_polls}: {exc}")
        time.sleep(2.0)
    print(f"  WARNING: Temporal workflow did not reach terminal state within {max_polls * 2}s")
    return {"error": "timeout", "workflow_id": workflow_id}


def main() -> int:
    if not OUTREACH_PYTHON.exists():
        print(f"ERROR: Outreach python not found at {OUTREACH_PYTHON}")
        return 1
    if not GLOBAL_VENV.exists():
        print(f"ERROR: Global venv python not found at {GLOBAL_VENV}")
        return 1

    _kill_zombie_services()

    for path in (DB_PATH, OUTREACH_LOG, GLOBAL_LOG):
        try:
            path.unlink()
        except (FileNotFoundError, PermissionError):
            pass

    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUTF8"] = "1"
    env["OUTREACH_MCP_PATH"] = str(OUTREACH_MCP_PATH)
    env["OUTREACH_PYTHON"] = str(OUTREACH_PYTHON)
    env["ORCHESTRATOR_MOCK"] = "true"
    env["DATABASE_PATH"] = str(DB_PATH)
    env["OUTREACH_DEFAULT_SENDER_COMPANY"] = "NudgeShield"
    env["OUTREACH_DEFAULT_SENDER_ELEVATOR_PITCH"] = "We help European insurers automate DORA, NIS2, and Solvency II compliance with AI-driven risk dashboards. Our platform cuts audit prep time by 70% and is trusted by 3 of Europe's top-10 insurers."
    env["OUTREACH_DEFAULT_OFFER_NAME"] = "DORA Compliance Accelerator"
    env["OUTREACH_DEFAULT_SOLUTION_SUMMARY"] = "90-day automated DORA gap analysis with real-time risk monitoring dashboards, automated evidence collection for auditors, and full DORA Article 15-20 coverage. Average 70% reduction in audit preparation time."
    env["OUTREACH_DEFAULT_CTA"] = "Book a 15-minute demo to see your DORA readiness score"

    outreach_proc: Optional[subprocess.Popen] = None
    global_proc: Optional[subprocess.Popen] = None
    outreach_log_file: Optional[io.BufferedWriter] = None
    global_log_file: Optional[io.BufferedWriter] = None
    success = False

    try:
        print("Starting Outreach Project services via Outreach-Project/main.py...")
        outreach_log_file = OUTREACH_LOG.open("wb")
        outreach_proc = subprocess.Popen(
            [str(sys.executable), str(OUTREACH_ROOT / "main.py")],
            cwd=str(OUTREACH_ROOT),
            env=env,
            stdout=outreach_log_file,
            stderr=subprocess.STDOUT,
        )

        print("Waiting for Temporal on port 7233...")
        _wait_for_socket(7233, timeout=120.0)
        print("Temporal is ready.")

        print("Waiting for Message Generator on port 8000...")
        _wait_for_http(8000, "/", timeout=180.0)
        print("Message Generator is ready.")

        print("Waiting for Sequence Generator on port 8001...")
        _wait_for_http(8001, "/health", timeout=180.0)
        print("Sequence Generator is ready.")

        print("Waiting for Outreach Orchestrator on port 8002...")
        _wait_for_http(8002, "/api/health", timeout=180.0)
        print("Outreach Orchestrator is ready.")

        print("Starting global orchestrator on port 8100...")
        global_log_file = GLOBAL_LOG.open("wb")
        global_proc = subprocess.Popen(
            [str(GLOBAL_VENV), "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8100"],
            cwd=str(GLOBAL_ROOT),
            env=env,
            stdout=global_log_file,
            stderr=subprocess.STDOUT,
        )

        print("Waiting for global orchestrator on port 8100...")
        _wait_for_http(8100, "/health", timeout=60.0)
        print("Global orchestrator is ready.")

        base = "http://localhost:8100/campaigns"

        print("\n[1] Saving params + starting campaign (mock Phase A, real Phase B)...")
        payload = {
            "user_id": "real-smoke-test-user",
            "icp_description_text": "European insurers and insurtechs with 200-5000 employees navigating DORA and NIS2 regulatory compliance deadlines, actively hiring security and compliance talent, with demonstrated budget for regulatory tooling.",
            "user_offering": "NudgeShield: AI-powered continuous cyber-risk assessment platform for insurers. We automate regulatory compliance (DORA/NIS2/Solvency II) with real-time risk dashboards, automated evidence collection, and board-ready reporting.",
            "sender_company": "NudgeShield",
            "offer_name": "DORA Compliance Accelerator",
            "solution_summary": "90-day automated DORA gap analysis with continuous risk monitoring. Full DORA Article 15-20 coverage, automated evidence collection, board-ready dashboards. 70% faster audit prep.",
            "cta": "Book a 15-minute demo to see your DORA readiness score",
            "run_async": False,
            "auto_start_outreach": False,
            "max_touches": 4,
            "max_days": 10,
            "preferred_first_channel": "linkedin_dm",
            "sequence_options": {
                "vary_tone": True,
                "include_breakup": True,
                "reference_previous": True,
                "escalate_urgency": True,
                "cross_channel": True,
            },
            "stage_instructions": {
                "first_touch": "Lead with the DORA compliance pain point. Do NOT pitch product yet.",
                "second_touch": "Reference Series B funding. Position NudgeShield as DORA accelerator.",
                "third_touch": "Mention EUR 2M budget and Fortune 500 insurer adoption. Include CTA.",
            },
            "personality_config": {
                "base_template": "consultative_ciso",
                "personality_traits": [
                    "concise and direct — respect the CISO's time",
                    "credible and well-researched — cite specific signals",
                    "warm but professional — build trust, not just urgency",
                    "DORA-literate — use regulatory terminology naturally",
                ],
                "always_include_phrases": [
                    "happy to share a case study",
                    "no pressure — just exploring fit",
                ],
                "never_use_phrases": [
                    "disrupt", "revolutionize", "game-changer",
                    "limited time offer", "act now", "don't miss out",
                ],
                "urgency_level": "low",
                "humor_sarcasm": False,
                "voice_samples": [
                    "Hi Sophie — saw your post about DORA compliance tooling. We recently helped a Paris-based insurer cut their audit prep from 6 weeks to 10 days using automated evidence collection. Would a 15-min walkthrough be useful? No pressure — just curious if there's overlap.",
                    "Quick follow-up, Sophie. I noticed CyberShield is hiring a DORA/NIS2 compliance analyst — we built our DORA dashboard specifically for teams ramping up regulatory readiness. Happy to share how it maps to Articles 15-20 if that's on your radar.",
                    "Last one from me — with the Jan 2027 DORA deadline and your EUR 2M H2 tooling budget, timing feels right for a quick look at NudgeShield. Fortune 500 insurers are using us to cut audit cycles by 70%. If it's not a priority right now, no worries at all.",
                ],
            },
        }
        r = httpx.post(f"{base}/params", json=payload, timeout=30.0)
        r.raise_for_status()
        _pprint("POST /campaigns/params", r.json())
        r = httpx.post(
            f"{base}/start",
            json={"user_id": "real-smoke-test-user"},
            timeout=30.0,
        )
        r.raise_for_status()
        campaign_resp = r.json()
        _pprint("POST /campaigns/start", campaign_resp)
        campaign_id = campaign_resp["campaign_id"]

        print("\n[2] Fetching campaign details...")
        r = httpx.get(f"{base}/{campaign_id}", timeout=10.0)
        r.raise_for_status()
        campaign_data = r.json()
        if not campaign_data.get("packages"):
            print("ERROR: No lead packages were generated in Phase A mock.")
            return 1
        _pprint("GET /campaigns/{id} (packages)", campaign_data["packages"][0])

        print("\n[3] Starting outreach via real stdio MCP...")
        r = httpx.post(f"{base}/{campaign_id}/outreach", timeout=10.0)
        r.raise_for_status()
        _pprint("POST /campaigns/{id}/outreach", r.json())

        print("\n[4] Polling for outreach threads (up to 10 min)...")
        threads = []
        data: dict = {}
        for attempt in range(600):
            try:
                r = httpx.get(f"{base}/{campaign_id}/outreach", timeout=10.0)
                r.raise_for_status()
                data = r.json()
                threads = data.get("threads", [])
                if threads:
                    break
                if attempt % 10 == 0:
                    print(f"  poll {attempt + 1}/600: no threads yet")
            except Exception as exc:
                print(f"  poll {attempt + 1}/600 error: {exc}")
            time.sleep(1.0)
        _pprint("GET /campaigns/{id}/outreach", data)

        if not threads:
            print("ERROR: No outreach threads were created within 10 minutes.")
            return 1

        thread_id = threads[0].get("thread_id")
        print(f"\n[5] Approving thread {thread_id}...")
        r = httpx.post(
            f"{base}/{campaign_id}/outreach/{thread_id}/approve",
            json={"approved": True},
            timeout=10.0,
        )
        r.raise_for_status()
        approve_data = r.json()
        _pprint("POST /campaigns/{id}/outreach/{thread_id}/approve", approve_data)

        # ── [5b] Query Temporal for generated messages ──────────────────
        twf_id = approve_data.get("temporal_workflow_id")
        if twf_id and not twf_id.startswith("SIMULATED"):
            print(f"\n[5b] Querying Temporal workflow {twf_id} for generated messages...")
            _query_temporal_workflow(twf_id, "after-first-dispatch")
        else:
            print(f"\n[5b] Skipping Temporal query (workflow_id={twf_id})")

        print("\n[6] Fetching outreach observability...")
        r = httpx.get(f"{base}/{campaign_id}/outreach/observability", timeout=10.0)
        r.raise_for_status()
        _pprint("GET /campaigns/{id}/outreach/observability", r.json())

        print("\n[7] Real end-to-end smoke test completed successfully.")
        print(f"    Campaign ID: {campaign_id}")
        print(f"    Thread ID:   {thread_id}")

        # ── [8] HITL: Reject + Regenerate ────────────────────────────
        print("\n[8] HITL: Rejecting with feedback to trigger regeneration...")
        r = httpx.post(
            f"{base}/{campaign_id}/outreach/{thread_id}/approve",
            json={
                "approved": False,
                "feedback": "Too aggressive — tone it down 50%, focus on DORA compliance pain point, mention the EUR 60M Series B from TechCrunch",
            },
            timeout=10.0,
        )
        r.raise_for_status()
        regen_resp = r.json()
        _pprint("POST /campaigns/{id}/outreach/{thread_id}/approve (REJECTED)", regen_resp)

        if regen_resp.get("status") != "regenerated":
            print(f"ERROR: Expected 'regenerated' status, got: {regen_resp.get('status')}")
            return 1
        print("[OK] Regeneration triggered successfully.")

        # ── [9] Regenerate loopback: poll for regenerated sequence ──
        print("\n[9] HITL: Polling for regenerated thread (loopback)...")
        regen_threads = []
        regen_data: dict = {}
        for attempt in range(60):
            try:
                r = httpx.get(f"{base}/{campaign_id}/outreach", timeout=10.0)
                r.raise_for_status()
                regen_data = r.json()
                regen_threads = regen_data.get("threads", [])
                # Find thread with regenerated_status or updated payload
                for t in regen_threads:
                    pl = t.get("payload", {})
                    resp = pl.get("response", {})
                    if resp.get("status") == "regenerated" or resp.get("status") == "awaiting_approval":
                        if resp.get("status") == "awaiting_approval" and attempt > 5:
                            regen_threads = [t]
                            break
                else:
                    time.sleep(1.0)
                    continue
                break
            except Exception as exc:
                print(f"  regen poll {attempt + 1}/60 error: {exc}")
            time.sleep(1.0)

        if not regen_threads:
            print("WARNING: No regenerated thread found. The LangGraph regen worked but the new thread wasn't stored.")
        else:
            regen_thread_id = regen_threads[0].get("thread_id")
            print(f"[OK] Found regenerated sequence at thread_id: {regen_thread_id}")
            _pprint("GET /campaigns/{id}/outreach (regenerated thread)", regen_data)

            # ── [10] Re-approve the regenerated sequence ─────────────────
            print(f"\n[10] HITL: Re-approving regenerated sequence {regen_thread_id}...")
            r = httpx.post(
                f"{base}/{campaign_id}/outreach/{regen_thread_id}/approve",
                json={"approved": True},
                timeout=10.0,
            )
            r.raise_for_status()
            re_approve_data = r.json()
            _pprint("POST /campaigns/{id}/outreach/{regenerated id}/approve (RE-APPROVED)", re_approve_data)

            # ── [10b] Query Temporal for regenerated messages ──────
            regen_twf_id = re_approve_data.get("temporal_workflow_id")
            if regen_twf_id and not regen_twf_id.startswith("SIMULATED"):
                print(f"\n[10b] Querying Temporal workflow {regen_twf_id} for regenerated messages...")
                _query_temporal_workflow(regen_twf_id, "after-regen-dispatch")
            else:
                print(f"\n[10b] Skipping Temporal query (workflow_id={regen_twf_id})")

        success = True
        return 0

    finally:
        print("\nShutting down services...")
        if global_proc is not None:
            _kill_tree(global_proc.pid)
        if outreach_proc is not None:
            _kill_tree(outreach_proc.pid)

        if outreach_log_file and not outreach_log_file.closed:
            outreach_log_file.close()
        if global_log_file and not global_log_file.closed:
            global_log_file.close()

        if success:
            for path in (DB_PATH, OUTREACH_LOG, GLOBAL_LOG):
                try:
                    path.unlink()
                except (FileNotFoundError, PermissionError):
                    pass
        else:
            print(f"\nLogs preserved for debugging:")
            print(f"  Outreach log: {OUTREACH_LOG}")
            print(f"  Global log:   {GLOBAL_LOG}")
            print(f"  Database:     {DB_PATH}")


if __name__ == "__main__":
    sys.exit(main())
