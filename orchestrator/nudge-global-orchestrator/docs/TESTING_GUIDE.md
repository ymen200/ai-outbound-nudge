# Testing Guide — Nudge Global Orchestrator

This guide covers all three test tiers: **unit tests**, **mock integration test**, and the **real end-to-end smoke test**. Each tier has different prerequisites and tells you something different about the system.

---

## Quick Reference

| Test | What it tests | Prerequisites | Command | Runtime |
|------|--------------|---------------|---------|---------|
| Unit tests | Payload mapping, client logic, timeout, retry | venv only | `pytest tests/ -v` | ~2s |
| Mock integration | Full handoff with fake MCP server | venv only | `python scripts/test_outreach_integration.py` | ~15s |
| Real smoke test | Full pipeline with real Gemini + all services | venvs + GOOGLE_API_KEY + Temporal CLI | `python scripts/test_outreach_real.py` | ~3-5 min |

---

## 1. Unit Tests

**What they cover:** Payload mapping, signal normalization, OutreachClient path guards, McpStdioClient timeout, retry + backoff logic, `start_outreach_for_campaign` success/failure paths. No subprocess, no network, no API keys.

**Prerequisites:**
- `nudge-global-orchestrator` venv set up
- Dependencies installed (`pip install -r requirements.txt`)

### Run all unit tests

```bash
cd nudge_ai_outbound_orchestrator/nudge-global-orchestrator
venv\Scripts\python -m pytest tests/ -v
```

### Expected output

```
tests/test_outreach_client.py::test_outreach_client_raises_when_mcp_path_missing PASSED
tests/test_outreach_client.py::test_outreach_client_warns_when_not_run_mcp PASSED
...
tests/test_outreach_client.py::test_mcp_stdio_client_negative_max_retries_raises_runtime_error PASSED
tests/test_outreach_mapping.py::test_web_profil_brut_coerces_dict_signals PASSED
...
tests/test_phase_a_mock.py::test_employee_ranges PASSED
...
===== 61 passed, 2 failed in 3.01s =====
```

**The 2 failures are pre-existing Phase A tests** (`test_build_final_packages_company_only_when_no_personas` and `test_mock_phase_a`). These are in Phase A code which is a separate ticket. All Phase B tests (47 in `test_outreach_client.py` + `test_outreach_mapping.py`) should pass.

### Run only Phase B tests (all should pass)

```bash
venv\Scripts\python -m pytest tests/test_outreach_client.py tests/test_outreach_mapping.py -v
```

**Expected:** `47 passed, 0 failed`

### Run with summary only (less verbose)

```bash
venv\Scripts\python -m pytest tests/ -q
```

### Run a single test

```bash
venv\Scripts\python -m pytest tests/test_outreach_client.py::test_mcp_stdio_client_timeout_raises_timeout_error -v
```

### Test files

| File | Total tests | What it covers |
|------|-------------|----------------|
| `tests/test_outreach_client.py` | 36 | OutreachClient path guards, tool delegation, `start_outreach_for_campaign` (success/failure/filtering), McpStdioClient timeout, retry + backoff, negative max_retries guard |
| `tests/test_outreach_mapping.py` | 11 | `build_outreach_payload` flat schema, `normalize_research_signals` (dict/list/string/None), `web_profil_brut` str() coercion, config resolution hierarchy |
| `tests/test_phase_a_mock.py` | 13 | Phase A domain mapping (ICP, companies, personas), mock pipeline — **2 pre-existing failures** (`test_build_final_packages_company_only_when_no_personas`, `test_mock_phase_a`) |
| `tests/test_usage_report.py` | 3 | Usage report aggregation (Apollo/Gemini/Groq token tracking) |

**Arithmetic check:** 36 + 11 + 13 + 3 = **63 total** → 61 passed + 2 failed. ✓

---

## 2. Mock Integration Test

**What it covers:** The full Phase B handoff (campaign creation → outreach start → thread creation → approval) using a **mock MCP server** instead of the real Outreach Orchestrator. No real services, no Gemini calls, no API keys.

**Prerequisites:**
- `nudge-global-orchestrator` venv set up
- Port 8100 available (the test starts a temporary global orchestrator)

### Run

```bash
cd nudge_ai_outbound_orchestrator/nudge-global-orchestrator
venv\Scripts\python scripts/test_outreach_integration.py
```

### What it does

1. Writes a mock MCP server script to `scripts/_outreach_mock_mcp.py`
2. Starts the global orchestrator on port 8100 with `ORCHESTRATOR_MOCK=true` (mock Phase A) and `OUTREACH_MCP_PATH` pointing to the mock MCP server
3. Creates a campaign (mock Phase A generates a fake lead package)
4. Starts outreach → the global orchestrator calls the mock MCP server's `run_outreach_pipeline` tool
5. Polls for the outreach thread → approves it
6. Verifies the captured payload that was sent to the mock MCP server
7. Cleans up (kills the orchestrator, deletes temp files)

### Expected output

```
Waiting for global orchestrator on port 8100...
[1] Creating campaign with manual outreach...
============================================================
POST /campaigns
============================================================
{ "campaign_id": "...", "status": "completed", ... }

[2] Fetching campaign details...
[3] Starting outreach...
[4] Polling for outreach threads...
[5] Approving thread mock-thread-123...
[6] Fetching outreach observability...
[7] Verifying captured run_outreach_pipeline payload...
[8] Integration test completed successfully.
```

### Troubleshooting

| Issue | Fix |
|-------|-----|
| `Port 8100 already in use` | Kill the process: `netstat -ano \| findstr :8100` → `taskkill /F /PID <pid>` |
| Test hangs at "Waiting for global orchestrator" | Check `venv\Scripts\python` exists and deps are installed |
| Mock MCP server fails to start | Ensure `fastmcp` is installed: `pip install fastmcp` |

---

## 3. Real End-to-End Smoke Test

**What it covers:** The **complete pipeline** with real services: Temporal, Message Generator, Sequence Generator, Outreach Orchestrator, and the Global Orchestrator. Uses **real Gemini API calls** (costs tokens). This is the most comprehensive test.

**Prerequisites:**

1. **Virtual environments** in all 4 projects:
   - `nudge-global-orchestrator/venv/`
   - `Outreach-Project/outreach orchestrator/venv/`
   - `Outreach-Project/sequence generator/venv/`
   - `Outreach-Project/message generator and sender/venv/`

2. **`.env` files with `GOOGLE_API_KEY`** in:
   - `Outreach-Project/sequence generator/.env`
   - `Outreach-Project/message generator and sender/.env`

3. **Temporal CLI** installed and on PATH:
   ```bash
   temporal --version    # should print a version
   ```
   Install: `winget install temporalio.cli` (Windows) or see [Temporal docs](https://docs.temporal.io/cli#install).

4. **Ports available**: 8000, 8001, 8002, 7233, 8100 (the script auto-kills zombies, but a clean start helps).

5. **No `.env` required** in `nudge-global-orchestrator/` — the script sets all env vars programmatically. It uses `ORCHESTRATOR_MOCK=true` for Phase A (mock lead data) and real Phase B (real outreach via MCP).

### Run

```bash
cd nudge_ai_outbound_orchestrator/nudge-global-orchestrator
venv\Scripts\python scripts/test_outreach_real.py
```

### What it does (step by step)

1. **Cleanup** — kills any processes listening on ports 8000, 8001, 8002, 7233, 8100
2. **Start Outreach Project services** — runs `Outreach-Project/main.py` which starts:
   - Temporal dev server (port 7233)
   - Message Generator (port 8000)
   - Sequence Generator (port 8001)
   - Outreach Orchestrator (port 8002)
   - Temporal Worker
3. **Wait for all services** — polls each port until ready (up to 180s per service)
4. **Start global orchestrator** — starts uvicorn on port 8100 with mock Phase A + real Phase B
5. **Create campaign** — `POST /campaigns` (mock Phase A generates a fake lead package)
6. **Start outreach** — `POST /campaigns/{id}/outreach` (triggers real MCP call to Outreach Orchestrator)
7. **Poll for threads** — `GET /campaigns/{id}/outreach` every 1s for up to 10 minutes (Gemini takes time)
8. **Approve thread** — `POST /campaigns/{id}/outreach/{thread_id}/approve` (dispatches to Temporal)
9. **Fetch observability** — `GET /campaigns/{id}/outreach/observability`
10. **Cleanup** — kills all spawned processes and their children

### Expected output (successful run)

```
Cleaning up any existing processes on test ports...
Starting Outreach Project services via Outreach-Project/main.py...
Waiting for Temporal on port 7233...
Temporal is ready.
Waiting for Message Generator on port 8000...
Message Generator is ready.
Waiting for Sequence Generator on port 8001...
Sequence Generator is ready.
Waiting for Outreach Orchestrator on port 8002...
Outreach Orchestrator is ready.
Starting global orchestrator on port 8100...
Waiting for global orchestrator on port 8100...
Global orchestrator is ready.

[1] Creating campaign (mock Phase A, real Phase B)...
============================================================
POST /campaigns
============================================================
{ "campaign_id": "xxxxxxxx-...", "status": "completed", ... }

[2] Fetching campaign details...
[3] Starting outreach via real stdio MCP...
[4] Polling for outreach threads (up to 10 min)...
  poll 1/600: no threads yet
  poll 11/600: no threads yet
  ...

============================================================
GET /campaigns/{id}/outreach
============================================================
{ "threads": [{ "thread_id": "api_thread_xxx", "status": "awaiting_approval" }] }

[5] Approving thread api_thread_xxx...
============================================================
POST /campaigns/{id}/outreach/{thread_id}/approve
============================================================
{ "status": "dispatched", "thread_id": "api_thread_xxx" }

[6] Fetching outreach observability...
[7] Real end-to-end smoke test completed successfully.
    Campaign ID: xxxxxxxx-...
    Thread ID:   api_thread_xxx

Shutting down services...
```

### If it fails

The script **preserves logs and the database** on failure for debugging:

```
Logs preserved for debugging:
  Outreach log: C:\Users\ASUS\AppData\Local\Temp\outreach_real_test_outreach.log
  Global log:   C:\Users\ASUS\AppData\Local\Temp\outreach_real_test_global.log
  Database:     C:\Users\ASUS\AppData\Local\Temp\orchestrator_real_test.db
```

### Troubleshooting

| Issue | Likely cause | Fix |
|-------|-------------|-----|
| `temporal not found` | Temporal CLI not installed | `winget install temporalio.cli` |
| Services don't start | Missing venv or deps in a submodule | Recreate venv + `pip install -r requirements.txt` in the failing submodule |
| `GOOGLE_API_KEY not configured` | Missing `.env` in sequence generator or message generator | Create `.env` with `GOOGLE_API_KEY=your_key` |
| Thread status `failed: Connection closed` | Outreach MCP server crashed at startup | Check the outreach log — likely an import error or missing dependency |
| Thread status `failed: Input validation error` | Payload sent `None` for a required string field | Check the global log for the `run_outreach_pipeline` arguments |
| Timeout after 10 minutes | Gemini is slow or the sequence is complex | Re-run; or increase the poll count in the script |
| Port already in use | Zombie process from a previous run | The script auto-kills zombies, but you can manually: `taskkill /F /IM temporal.exe` and `taskkill /F /IM python.exe` |
| Redis unreachable (warning) | Redis not running | This is a **warning, not an error** — the Message Generator falls back to in-memory storage. For production, start Redis via `docker-compose up redis` |

### Manual alternative (if the script is stubborn)

If the automated script keeps failing, you can run the services manually in separate terminals to see each service's output:

**Terminal 1 — Outreach services:**
```powershell
cd Outreach-Project
$env:PYTHONIOENCODING="utf-8"
$env:PYTHONUTF8="1"
python main.py
```

**Terminal 2 — Global orchestrator:**
```powershell
cd nudge_ai_outbound_orchestrator\nudge-global-orchestrator
$env:ORCHESTRATOR_MOCK="true"
$env:OUTREACH_MCP_PATH=(Resolve-Path ..\..\Outreach-Project\"outreach orchestrator"\run_mcp.py)
$env:OUTREACH_PYTHON=(Resolve-Path ..\..\Outreach-Project\"outreach orchestrator"\venv\Scripts\python.exe)
venv\Scripts\python -m uvicorn app.main:app --host 0.0.0.0 --port 8100
```

**Terminal 3 — Run the handoff:**
```powershell
# Create campaign
curl -X POST http://localhost:8100/campaigns -H "Content-Type: application/json" -d "{\"user_id\":\"smoke\",\"run_async\":false,\"auto_start_outreach\":false}"

# Start outreach (replace {campaign_id})
curl -X POST http://localhost:8100/campaigns/{campaign_id}/outreach

# Poll for threads (repeat until you see a thread)
curl http://localhost:8100/campaigns/{campaign_id}/outreach

# Approve (replace {thread_id})
curl -X POST http://localhost:8100/campaigns/{campaign_id}/outreach/{thread_id}/approve -H "Content-Type: application/json" -d "{\"approved\":true}"
```

---

## Environment Checklist

Before running any test, verify:

```bash
# 1. Global orchestrator venv
cd nudge_ai_outbound_orchestrator\nudge-global-orchestrator
venv\Scripts\python --version          # Python 3.12+
venv\Scripts\python -m pytest --version # pytest installed

# 2. Outreach Project venvs (for real smoke test only)
..\..\Outreach-Project\"outreach orchestrator"\venv\Scripts\python --version
..\..\Outreach-Project\"sequence generator"\venv\Scripts\python --version
..\..\Outreach-Project\"message generator and sender"\venv\Scripts\python --version

# 3. Temporal CLI (for real smoke test only)
temporal --version

# 4. GOOGLE_API_KEY (for real smoke test only)
# Check Outreach-Project/sequence generator/.env has GOOGLE_API_KEY=...
# Check Outreach-Project/message generator and sender/.env has GOOGLE_API_KEY=...
```

---

## CI/CD (not yet set up)

There is no CI pipeline configured. To add one, a minimal GitHub Actions workflow would be:

```yaml
# .github/workflows/tests.yml
name: Tests
on: [push, pull_request]
jobs:
  unit-tests:
    runs-on: windows-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with: { python-version: "3.12" }
      - run: pip install -r nudge_ai_outbound_orchestrator/nudge-global-orchestrator/requirements.txt
      - run: cd nudge_ai_outbound_orchestrator/nudge-global-orchestrator && python -m pytest tests/test_outreach_client.py tests/test_outreach_mapping.py -v
```

The real smoke test should NOT run in CI (it requires real API keys and external services).
