"""
Self-contained integration test for the global orchestrator -> Outreach Orchestrator handoff
using stdio MCP (not REST).

Starts the global orchestrator API on port 8100 in ORCHESTRATOR_MOCK mode. The global
orchestrator spawns a mock Outreach MCP server via stdio, so no real Outreach services
or API keys are needed.

Run from the nudge-global-orchestrator directory:
    venv/Scripts/python scripts/test_outreach_integration.py
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent.parent
VENV_PYTHON = ROOT / "venv" / "Scripts" / "python.exe"
if not VENV_PYTHON.exists():
    VENV_PYTHON = ROOT / "venv" / "bin" / "python"
    if not VENV_PYTHON.exists():
        VENV_PYTHON = ROOT / "venv" / "Scripts" / "python"

# ---------------------------------------------------------------------------
# Mock Outreach MCP server (stdio)
# ---------------------------------------------------------------------------

MOCK_MCP_APP = ROOT / "scripts" / "_outreach_mock_mcp.py"

_MOCK_MCP_SOURCE = '''
import asyncio
import json
import os
from pathlib import Path

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import Tool, TextContent

app = Server("mock-outreach-orchestrator")
CAPTURE_PATH = Path(os.environ.get("MOCK_CAPTURE_PATH", "/tmp/outreach_mock_captured.json"))


def _merge_capture(key: str, value: dict) -> None:
    try:
        if CAPTURE_PATH.exists():
            existing = json.loads(CAPTURE_PATH.read_text(encoding="utf-8"))
        else:
            existing = {}
        existing[key] = value
        CAPTURE_PATH.write_text(json.dumps(existing, indent=2, default=str), encoding="utf-8")
    except Exception:
        pass


@app.list_tools()
async def list_tools() -> list[Tool]:
    return [
        Tool(name="run_outreach_pipeline", inputSchema={"type": "object", "properties": {}}),
        Tool(name="approve_pipeline", inputSchema={"type": "object", "properties": {}}),
        Tool(name="get_outreach_status", inputSchema={"type": "object", "properties": {}}),
        Tool(name="get_observability", inputSchema={"type": "object", "properties": {}}),
    ]


@app.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    if name == "run_outreach_pipeline":
        _merge_capture("run", arguments)
        return [TextContent(
            type="text",
            text=json.dumps({"status": "awaiting_approval", "thread_id": "mock-thread-123"}),
        )]
    if name == "approve_pipeline":
        _merge_capture("approve", arguments)
        return [TextContent(
            type="text",
            text=json.dumps({"status": "dispatched", "thread_id": arguments.get("thread_id")}),
        )]
    if name == "get_outreach_status":
        return [TextContent(
            type="text",
            text=json.dumps({"status": "ok"}),
        )]
    if name == "get_observability":
        return [TextContent(
            type="text",
            text=json.dumps({"module": "outreach", "total_tokens": 42}),
        )]
    return [TextContent(
        type="text",
        text=json.dumps({"error": f"unknown tool {name}"}),
    )]


async def main():
    async with stdio_server() as (read_stream, write_stream):
        await app.run(read_stream, write_stream, app.create_initialization_options())


if __name__ == "__main__":
    asyncio.run(main())
'''

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def wait_for(url: str, timeout: float = 10.0) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            r = httpx.get(url, timeout=1.0)
            if r.status_code == 200:
                return
        except Exception:
            pass
        time.sleep(0.3)
    raise RuntimeError(f"Service at {url} did not become ready within {timeout}s")


def pprint(title: str, data) -> None:
    print(f"\n{'='*60}")
    print(title)
    print("=" * 60)
    print(json.dumps(data, indent=2, default=str))


# ---------------------------------------------------------------------------
# Main test
# ---------------------------------------------------------------------------

def main() -> int:
    # Write the mock MCP server script only when the test actually runs
    # (not at import time, which would create side effects for collectors).
    MOCK_MCP_APP.write_text(_MOCK_MCP_SOURCE, encoding="utf-8")

    # Use a temp DB so we don't touch any existing orchestrator.db
    db_path = Path(tempfile.gettempdir()) / "orchestrator_integration_test.db"
    db_path.unlink(missing_ok=True)
    capture_path = Path(tempfile.gettempdir()) / "outreach_mock_captured.json"
    capture_path.unlink(missing_ok=True)

    env = os.environ.copy()
    env["ORCHESTRATOR_MOCK"] = "true"
    env["DATABASE_PATH"] = str(db_path)
    env["OUTREACH_MCP_PATH"] = str(MOCK_MCP_APP)
    env["OUTREACH_PYTHON"] = str(VENV_PYTHON)
    env["MOCK_CAPTURE_PATH"] = str(capture_path)
    env["OUTREACH_DEFAULT_SENDER_COMPANY"] = "NudgeShield"
    env["OUTREACH_DEFAULT_OFFER_NAME"] = "Cyber-Risk Audit"
    env["OUTREACH_DEFAULT_SOLUTION_SUMMARY"] = "Quick cyber-risk snapshot"
    env["OUTREACH_DEFAULT_CTA"] = "Reply to book a call"

    global_proc = subprocess.Popen(
        [str(VENV_PYTHON), "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8100"],
        cwd=str(ROOT),
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )

    try:
        print("Waiting for global orchestrator on port 8100...")
        wait_for("http://localhost:8100/health")

        base = "http://localhost:8100/campaigns"

        # 1. Save params then start campaign (sync so we get the package back)
        print("\n[1] Saving campaign params and starting with manual outreach...")
        payload = {
            "user_id": "integration-test-user",
            "icp_description_text": "Mid-market insurance firms in the US",
            "user_offering": "NudgeShield cyber-risk analytics",
            "sender_company": "NudgeShield",
            "offer_name": "Cyber-Risk Audit",
            "solution_summary": "Quick snapshot",
            "cta": "Reply to book a call",
            "run_async": False,
            "auto_start_outreach": False,
        }
        r = httpx.post(f"{base}/params", json=payload, timeout=30.0)
        r.raise_for_status()
        pprint("POST /campaigns/params", r.json())
        r = httpx.post(
            f"{base}/start",
            json={"user_id": "integration-test-user"},
            timeout=30.0,
        )
        r.raise_for_status()
        campaign_resp = r.json()
        pprint("POST /campaigns/start", campaign_resp)
        campaign_id = campaign_resp["campaign_id"]

        # 2. Fetch campaign and inspect lead package + outreach threads
        print("\n[2] Fetching campaign details...")
        r = httpx.get(f"{base}/{campaign_id}", timeout=10.0)
        r.raise_for_status()
        campaign_data = r.json()
        pprint("GET /campaigns/{id}", campaign_data)

        if not campaign_data.get("packages"):
            print("ERROR: No lead packages were generated in Phase A mock.")
            return 1

        # 3. Manually start outreach
        print("\n[3] Starting outreach...")
        r = httpx.post(f"{base}/{campaign_id}/outreach", timeout=10.0)
        r.raise_for_status()
        pprint("POST /campaigns/{id}/outreach", r.json())

        # Background task runs asynchronously; poll for thread records
        print("\n[4] Polling for outreach threads...")
        for _ in range(20):
            r = httpx.get(f"{base}/{campaign_id}/outreach", timeout=10.0)
            r.raise_for_status()
            threads = r.json().get("threads", [])
            if threads:
                break
            time.sleep(0.5)
        pprint("GET /campaigns/{id}/outreach", r.json())

        if not threads:
            print("ERROR: No outreach threads were created.")
            return 1

        thread_id = threads[0].get("thread_id")
        print(f"\n[5] Approving thread {thread_id}...")
        r = httpx.post(
            f"{base}/{campaign_id}/outreach/{thread_id}/approve",
            json={"approved": True},
            timeout=10.0,
        )
        r.raise_for_status()
        pprint("POST /campaigns/{id}/outreach/{thread_id}/approve", r.json())

        # 6. Observability relay
        print("\n[6] Fetching outreach observability...")
        r = httpx.get(f"{base}/{campaign_id}/outreach/observability", timeout=10.0)
        r.raise_for_status()
        pprint("GET /campaigns/{id}/outreach/observability", r.json())

        # 7. Verify the payload delivered to the mock outreach MCP server
        print("\n[7] Verifying captured run_outreach_pipeline payload...")
        captured = json.loads(capture_path.read_text(encoding="utf-8"))
        pprint("Captured run_outreach_pipeline payload from global orchestrator", captured)

        print("\n[8] Integration test completed successfully.")
        print(f"    Campaign ID: {campaign_id}")
        print(f"    Thread ID:   {thread_id}")
        return 0

    finally:
        global_proc.terminate()
        try:
            global_proc.wait(timeout=5)
        except Exception:
            global_proc.kill()
        db_path.unlink(missing_ok=True)
        capture_path.unlink(missing_ok=True)
        try:
            MOCK_MCP_APP.unlink()
        except Exception:
            pass


if __name__ == "__main__":
    sys.exit(main())
